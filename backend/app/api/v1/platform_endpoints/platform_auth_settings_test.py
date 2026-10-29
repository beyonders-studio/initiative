"""Which ways in the deployment permits."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import UserRole
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.testing.audit import emitted
from app.testing import (
    create_guild_provider_connection,
    create_auth_provider,
    create_federated_identity,
    create_guild,
    create_guild_auth_policy,
    create_user,
    get_auth_headers,
)
from app.core.rules import SignInRequirement
from app.services.platform import rules


URL = "/api/v1/settings/auth/platform"


async def _owner(session: AsyncSession):
    owner = await create_user(session, role=UserRole.owner)
    return owner, get_auth_headers(owner)


async def _can_send_mail(session: AsyncSession) -> None:
    """A deployment that can send, which the emailed code asks for."""
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.smtp_host = "smtp.example.com"
    row.smtp_from_address = "noreply@example.com"
    session.add(row)
    await session.commit()


async def _cannot_send_mail(session: AsyncSession) -> None:
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.smtp_host = None
    session.add(row)
    await session.commit()


async def _store_passkey(session: AsyncSession, user, *, credential_id: bytes) -> None:
    """Give the account a registered credential — a way in of its own."""
    from app.services.auth import passkeys as passkey_service

    await passkey_service.store(
        session,
        user_id=user.id,
        registered=passkey_service.RegisteredCredential(
            credential_id=credential_id,
            public_key=b"public-key-bytes",
            sign_count=0,
            aaguid=None,
            user_verified=True,
            backed_up=False,
            transports=["internal"],
        ),
        name="Key",
    )
    await session.commit()


async def test_read_reports_every_method_and_its_cost(
    client: AsyncClient, session: AsyncSession
):
    """Every method is listed whether or not it is on, each with the number
    withdrawing it would concern."""
    _, headers = await _owner(session)

    got = await client.get(URL, headers=headers)
    assert got.status_code == 200
    assert {m["method"] for m in got.json()["methods"]} == {
        "password",
        "sso",
        "totp",
        "passkey",
        "email_otp",
    }
    # Everything an account has to opt into is on; the emailed code, which
    # every account with an address could use at once, waits to be turned on.
    assert {m["method"] for m in got.json()["methods"] if m["enabled"]} == {
        "password",
        "sso",
        "totp",
        "passkey",
    }
    assert got.json()["communities_requiring_sign_in"] == 0


async def test_at_least_one_way_in_must_remain(
    client: AsyncClient, session: AsyncSession
):
    _, headers = await _owner(session)
    put = await client.patch(URL, headers=headers, json={"methods": []})
    assert put.status_code == 422


async def test_withdrawing_a_method_reports_who_it_strands(
    client: AsyncClient, session: AsyncSession
):
    """Withdrawing SSO while an account signs in only that way is reported with
    the count, and proceeds when the caller echoes that exact number."""
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    refused = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"

    stale = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password"], "acknowledge_stranded": 99},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "SETTINGS_LOGIN_METHODS_STALE_ACK"

    accepted = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password"], "acknowledge_stranded": 1},
    )
    assert accepted.status_code == 200
    enabled = {m["method"] for m in accepted.json()["methods"] if m["enabled"]}
    assert enabled == {"password"}


async def test_the_account_making_the_change_cannot_strand_itself(
    client: AsyncClient, session: AsyncSession
):
    """The owner holding only a password cannot withdraw it, whatever number
    comes back: they add another way in first, and then it goes through."""
    owner, headers = await _owner(session)

    refused = await client.patch(URL, headers=headers, json={"methods": ["sso"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND_SELF"
    assert "X-Affected-Count" not in refused.headers

    acknowledged = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["sso"], "acknowledge_stranded": 1},
    )
    assert acknowledged.status_code == 409, acknowledged.text
    assert acknowledged.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND_SELF"

    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, owner, provider=provider)
    put = await client.patch(URL, headers=headers, json={"methods": ["sso"]})
    assert put.status_code == 200, put.text


async def test_withdrawing_sso_waits_for_guild_requirements(
    client: AsyncClient, session: AsyncSession
):
    """A guild requiring a sign-in through a provider of its own is reported
    with its count. A requirement is enforced from its policy row and stands on
    its own, so it is lifted first and the withdrawal then goes through."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    await create_guild_auth_policy(session, guild, provider)

    refused = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_COMMUNITY_POLICIES"
    assert refused.headers["X-Affected-Count"] == "1"

    got = await client.get(URL, headers=headers)
    assert got.json()["communities_requiring_sign_in"] == 1

    await rules.put(session, "auth_policy", SignInRequirement(), guild_id=guild.id)
    await session.commit()

    allowed = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert allowed.status_code == 200


async def test_a_guild_only_identity_is_counted_when_sso_is_withdrawn(
    client: AsyncClient, session: AsyncSession
):
    """Withdrawing single sign-on closes the guild-addressed login route as
    well as the platform one, so an account reached only through a guild's
    provider is one the count has to report."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="guild")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    refused = await client.patch(URL, headers=headers, json={"methods": ["password"]})

    assert refused.status_code == 409
    assert refused.headers["X-Affected-Count"] == "1"


async def test_withdrawing_a_method_nobody_uses_needs_no_acknowledgement(
    client: AsyncClient, session: AsyncSession
):
    _, headers = await _owner(session)
    put = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200
    enabled = {m["method"] for m in put.json()["methods"] if m["enabled"]}
    assert enabled == {"password"}


async def test_withdrawing_sso_closes_the_provider_routes(
    client: AsyncClient, session: AsyncSession
):
    """Server-side, not merely hidden: the listing empties and the login route
    refuses."""
    _, headers = await _owner(session)
    await create_auth_provider(session, slug="corp")

    listed = await client.get("/api/v1/auth/providers")
    assert any(p["slug"] == "corp" for p in listed.json()["providers"])

    put = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200

    assert (await client.get("/api/v1/auth/providers")).json()["providers"] == []
    login = await client.get("/api/v1/auth/corp/login", follow_redirects=False)
    assert login.status_code == 404


async def test_withdrawing_sso_closes_a_guilds_provider_routes_too(
    client: AsyncClient, session: AsyncSession
):
    """The guild-addressed listing and login go with it."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    theirs = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=theirs)

    listed = await client.get(f"/api/v1/auth/c/{guild.id}/providers")
    assert any(p["slug"] == "corp" for p in listed.json()["providers"])

    put = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert put.status_code == 200

    after = await client.get(f"/api/v1/auth/c/{guild.id}/providers")
    assert after.json()["providers"] == []
    login = await client.get(
        f"/api/v1/auth/c/{guild.id}/corp/login", follow_redirects=False
    )
    assert login.status_code == 404


async def test_withdrawing_password_closes_its_routes(
    client: AsyncClient, session: AsyncSession
):
    """The sign-in, the registration that mints one, and every half of reset."""
    owner, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, owner, provider=provider)
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    put = await client.patch(URL, headers=headers, json={"methods": ["sso"]})
    assert put.status_code == 200, put.text

    token = await client.post(
        "/api/v1/auth/token",
        data={"username": "someone@example.com", "password": "whatever"},
    )
    assert token.status_code == 403
    assert token.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"

    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "username": "newperson",
            "password": "a-long-enough-password-1",
        },
    )
    assert register.status_code == 403

    forgot = await client.post(
        "/api/v1/auth/password/forgot", json={"email": "someone@example.com"}
    )
    assert forgot.status_code == 403

    # An operator mailing someone a reset link is the same errand.
    mailed = await client.post(
        f"/api/v1/operator/users/{member.id}/reset-password", headers=headers
    )
    assert mailed.status_code == 403
    assert mailed.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"


async def test_an_account_with_only_a_guild_provider_counts_as_signed_in(
    client: AsyncClient, session: AsyncSession
):
    """A guild-scoped provider answers logins, so an account holding only one
    is not counted as stranded by withdrawing the password."""
    owner, headers = await _owner(session)
    guild = await create_guild(session, creator=owner)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    before = await client.get(URL, headers=headers)
    baseline = next(m for m in before.json()["methods"] if m["method"] == "password")[
        "would_strand"
    ]

    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    after = await client.get(URL, headers=headers)
    password = next(m for m in after.json()["methods"] if m["method"] == "password")
    # A guild-scoped provider answers logins, so the member it linked is a way
    # in rather than an account the password is holding up.
    assert password["would_strand"] == baseline


async def test_withdrawing_a_method_signs_nobody_out(
    client: AsyncClient, session: AsyncSession
):
    """Sessions already open keep working; this gates opening a new one."""
    owner, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, owner, provider=provider)
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    put = await client.patch(URL, headers=headers, json={"methods": ["sso"]})
    assert put.status_code == 200, put.text

    still_in = await client.get(URL, headers=headers)
    assert still_in.status_code == 200


async def test_the_surface_needs_the_config_capability(
    client: AsyncClient, session: AsyncSession
):
    member = await create_user(session, role=UserRole.member)
    headers = get_auth_headers(member)

    assert (await client.get(URL, headers=headers)).status_code == 403
    methods = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert methods.status_code == 403


@pytest.mark.parametrize("half", ["", "guest_"], ids=["members", "guests"])
async def test_withdrawing_sso_counts_a_guild_that_requires_a_method(
    client: AsyncClient, session: AsyncSession, half: str
):
    """A requirement can name a way in rather than a provider, and the guard
    that holds single sign-on back has to see both kinds, of members and of
    guests."""
    _, headers = await _owner(session)
    guild = await create_guild(session)
    await create_guild_auth_policy(
        session, guild, guest=half == "guest_", methods=[LoginMethod.sso]
    )

    refused = await client.patch(URL, headers=headers, json={"methods": ["password"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_COMMUNITY_POLICIES"
    assert refused.headers["X-Affected-Count"] == "1"


async def test_something_that_can_begin_a_session_must_remain(
    client: AsyncClient, session: AsyncSession
):
    """A tick is not enough on its own. An authenticator code accompanies a
    sign-in rather than opening one, so a deployment left with only that offers
    no way to begin."""
    _, headers = await _owner(session)

    put = await client.patch(URL, headers=headers, json={"methods": ["totp"]})
    assert put.status_code == 400
    assert put.json()["detail"] == "SETTINGS_LOGIN_METHODS_NO_PRIMARY"


async def test_withdrawing_the_authenticator_strands_nobody(
    client: AsyncClient, session: AsyncSession
):
    """It is nobody's only way in, so it goes without an acknowledgement — what
    it costs is that the factor stops being asked for, not anybody's access."""
    _, headers = await _owner(session)

    put = await client.patch(
        URL, headers=headers, json={"methods": ["password", "sso"]}
    )
    assert put.status_code == 200, put.text
    assert {m["method"] for m in put.json()["methods"] if m["enabled"]} == {
        "password",
        "sso",
    }


async def test_withdrawing_passkeys_reports_who_it_strands(
    client: AsyncClient, session: AsyncSession
):
    """An account holding a credential and nothing else is one the method is
    holding up, so it is reported with the count like the others."""
    _, headers = await _owner(session)
    holder = await create_user(session, hashed_password=None)
    await _store_passkey(session, holder, credential_id=b"stranded-credential")

    keep_the_rest = {"methods": ["password", "sso", "totp"]}
    refused = await client.patch(URL, headers=headers, json=keep_the_rest)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"

    accepted = await client.patch(
        URL,
        headers=headers,
        json={**keep_the_rest, "acknowledge_stranded": 1},
    )
    assert accepted.status_code == 200, accepted.text
    assert {m["method"] for m in accepted.json()["methods"] if m["enabled"]} == {
        "password",
        "sso",
        "totp",
    }


async def test_passkeys_alone_can_begin_a_session(
    client: AsyncClient, session: AsyncSession
):
    """A deployment may offer them and nothing else: a passkey opens a session
    by itself, which is what the rule asks for."""
    owner, headers = await _owner(session)
    await _store_passkey(session, owner, credential_id=b"owner-credential")

    put = await client.patch(URL, headers=headers, json={"methods": ["passkey"]})
    assert put.status_code == 200, put.text
    assert {m["method"] for m in put.json()["methods"] if m["enabled"]} == {"passkey"}


async def test_withdrawing_two_ways_in_at_once_counts_them_together(
    client: AsyncClient, session: AsyncSession
):
    """An account holding a password and a credential is stranded by the two
    going together and by neither alone, so the figure it is refused with is
    taken over the whole write rather than one method at a time."""
    owner, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, owner, provider=provider)
    holder = await create_user(session)
    await _store_passkey(session, holder, credential_id=b"two-ways-in")

    read = await client.get(URL, headers=headers)
    per_method = {m["method"]: m["would_strand"] for m in read.json()["methods"]}
    # Either one alone leaves them the other.
    assert per_method["passkey"] == 0

    refused = await client.patch(URL, headers=headers, json={"methods": ["sso"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    counted = int(refused.headers["X-Affected-Count"])
    assert counted == per_method["password"] + 1

    stale = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["sso"], "acknowledge_stranded": per_method["password"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "SETTINGS_LOGIN_METHODS_STALE_ACK"

    accepted = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["sso"], "acknowledge_stranded": counted},
    )
    assert accepted.status_code == 200, accepted.text
    assert {m["method"] for m in accepted.json()["methods"] if m["enabled"]} == {"sso"}


# ── What the deployment asks of an account ─────────────────────────────────


async def _enrol(session: AsyncSession, user) -> None:
    """Give the account an authenticator it has proved."""
    from datetime import datetime, timezone

    from app.models.platform.user_totp import UserTotp

    session.add(UserTotp(user_id=user.id, confirmed_at=datetime.now(timezone.utc)))
    await session.commit()


async def test_the_column_default_is_the_set_the_code_names(session: AsyncSession):
    """What a fresh row gets, as the database itself holds it.

    ``DEFAULT_LOGIN_METHODS`` feeds the model's ``server_default``, so those two
    cannot disagree. The live column default is a third thing — written by a
    migration, and not reissued when the tuple changes — so it is read back
    from the catalogue rather than assumed.
    """
    from sqlalchemy import text

    from app.core.login_methods import DEFAULT_LOGIN_METHODS

    rendered = await session.scalar(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'app_settings' "
            "AND column_name = 'login_methods'"
        )
    )
    assert rendered, "the column has no default"
    stored = rendered[rendered.index("{") + 1 : rendered.index("}")]
    assert {v.strip().strip("\"'") for v in stored.split(",")} == {
        m.value for m in DEFAULT_LOGIN_METHODS
    }


async def test_the_emailed_code_needs_a_way_to_send_mail(
    client: AsyncClient, session: AsyncSession
):
    """It is the one way in the deployment delivers itself, so it asks that
    the deployment can send."""
    _, headers = await _owner(session)

    refused = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey", "email_otp"]},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_NO_EMAIL"


async def test_the_emailed_code_is_permitted_once_mail_works(
    client: AsyncClient, session: AsyncSession
):
    _, headers = await _owner(session)
    await _can_send_mail(session)

    put = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey", "email_otp"]},
    )

    assert put.status_code == 200, put.text
    assert "email_otp" in {m["method"] for m in put.json()["methods"] if m["enabled"]}


async def test_withdrawing_the_emailed_code_needs_no_mail_server(
    client: AsyncClient, session: AsyncSession
):
    """The check is on the way up only: an operator who has since stopped
    sending mail can still take the method back off."""
    _, headers = await _owner(session)
    await _can_send_mail(session)
    await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey", "email_otp"]},
    )
    await _cannot_send_mail(session)

    put = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey"]},
    )

    assert put.status_code == 200, put.text
    assert "email_otp" not in {
        m["method"] for m in put.json()["methods"] if m["enabled"]
    }


async def test_an_address_is_a_way_in_once_the_code_is_permitted(
    client: AsyncClient, session: AsyncSession
):
    """With the emailed code on, an account holding nothing but its address
    still has a way in, so withdrawing the others strands nobody."""
    _, headers = await _owner(session)
    await _can_send_mail(session)
    await create_user(session, hashed_password=None)
    await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey", "email_otp"]},
    )

    put = await client.patch(URL, headers=headers, json={"methods": ["email_otp"]})

    assert put.status_code == 200, put.text
    assert {m["method"] for m in put.json()["methods"] if m["enabled"]} == {"email_otp"}


async def test_a_placeholder_address_is_not_a_way_in(
    client: AsyncClient, session: AsyncSession
):
    """An identity provider that sends no address leaves the account a
    ``{subject}@oidc.local`` placeholder, which no code reaches: leaving the
    emailed code as its only method strands it."""
    from sqlmodel import select

    from app.models.platform.user_email import UserEmail
    from app.services.auth import addresses

    _, headers = await _owner(session)
    await _can_send_mail(session)
    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)
    for row in (
        await session.exec(select(UserEmail).where(UserEmail.user_id == member.id))
    ).all():
        row.source = addresses.SOURCE_SYNTHETIC
        session.add(row)
    await session.commit()
    everything = ["password", "sso", "totp", "passkey", "email_otp"]
    await client.patch(URL, headers=headers, json={"methods": everything})

    refused = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "totp", "passkey", "email_otp"]},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"


async def test_withdrawing_the_emailed_code_reports_who_it_strands(
    client: AsyncClient, session: AsyncSession
):
    """Taking it back off is the write that costs something: an account that
    let its password go has nothing else."""
    _, headers = await _owner(session)
    await _can_send_mail(session)
    await create_user(session, hashed_password=None)
    await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey", "email_otp"]},
    )

    refused = await client.patch(
        URL,
        headers=headers,
        json={"methods": ["password", "sso", "totp", "passkey"]},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_WOULD_STRAND"
    assert refused.headers["X-Affected-Count"] == "1"


async def test_the_read_says_who_is_asked_and_what_it_would_cost(
    client: AsyncClient, session: AsyncSession
):
    """Both figures on every read, so the page states the consequence before
    the write rather than after it binds anybody."""
    owner, headers = await _owner(session)
    await create_user(session)

    answered = await client.get(URL, headers=headers)

    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["second_factor_requirement"] == "nobody"
    # The owner holds nothing yet, and neither does the account beside them.
    assert body["accounts_without_factor"]["platform_roles"] >= 1
    assert (
        body["accounts_without_factor"]["everyone"]
        > body["accounts_without_factor"]["platform_roles"]
    )


async def test_an_owner_who_holds_a_factor_may_ask_for_one(
    client: AsyncClient, session: AsyncSession
):
    owner, headers = await _owner(session)
    await _enrol(session, owner)

    written = await client.patch(
        URL, headers=headers, json={"second_factor_requirement": "everyone"}
    )

    assert written.status_code == 200, written.text
    assert written.json()["second_factor_requirement"] == "everyone"


async def test_the_last_way_to_answer_is_not_withdrawn_from_under_it(
    client: AsyncClient, session: AsyncSession
):
    """Lower the rule first, then withdraw the method — the order a
    community's requirement asks for too."""
    owner, headers = await _owner(session)
    await _enrol(session, owner)
    await client.patch(
        URL, headers=headers, json={"second_factor_requirement": "everyone"}
    )

    refused = await client.patch(
        URL, headers=headers, json={"methods": ["password", "sso"]}
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHODS_FACTOR_REQUIRED"

    lowered = await client.patch(
        URL, headers=headers, json={"second_factor_requirement": "nobody"}
    )
    assert lowered.status_code == 200, lowered.text
    withdrawn = await client.patch(
        URL, headers=headers, json={"methods": ["password", "sso"]}
    )
    assert withdrawn.status_code == 200, withdrawn.text


async def test_the_change_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner, headers = await _owner(session)
    await _enrol(session, owner)
    capfd.readouterr()
    await client.patch(
        URL, headers=headers, json={"second_factor_requirement": "everyone"}
    )

    rows = emitted(capfd, AuditEventType.PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED)

    assert len(rows) == 1
    assert rows[0]["detail"] == {"from": "nobody", "to": "everyone"}


async def test_several_rules_change_together(
    client: AsyncClient, session: AsyncSession
):
    owner, headers = await _owner(session)
    await _enrol(session, owner)

    written = await client.patch(
        URL,
        headers=headers,
        json={"second_factor_requirement": "everyone", "session_max_hours": 12},
    )

    assert written.status_code == 200, written.text
    assert written.json()["second_factor_requirement"] == "everyone"
    assert written.json()["session_max_hours"] == 12


async def test_a_refused_rule_leaves_the_others_as_they_were(
    client: AsyncClient, session: AsyncSession
):
    """One change: the limit beside a requirement its writer does not meet is
    not written either."""
    owner, headers = await _owner(session)

    refused = await client.patch(
        URL,
        headers=headers,
        json={"session_max_hours": 12, "second_factor_requirement": "everyone"},
    )
    assert refused.status_code == 400, refused.text

    read = (await client.get(URL, headers=headers)).json()
    assert read["session_max_hours"] is None
    assert read["second_factor_requirement"] == "nobody"
