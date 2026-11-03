"""What the deployment asks of an account, and what answers it.

A community asks what *this session* proved. The deployment asks what the
*account* holds — so a credential that cannot present anything, the app on a
phone or a personal API key, answers by its owner holding a factor rather than
by being refused for good.

The rule is decided twice, here and in ``public.platform_factor_satisfied()``,
and the two have to agree; the last section asks the database directly.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import SecondFactorRequirement
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.platform.api_key import UserApiKey
from app.models.platform.user_totp import UserTotp
from app.services.platform import api_keys as api_keys_service
from app.services.platform import rules
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_auth_token,
)


ME_URL = "/api/v1/me"
GUILDS_URL = "/api/v1/communities/"


async def _ask(session: AsyncSession, level: SecondFactorRequirement) -> None:
    """Make the deployment ask this of its accounts."""
    await rules.put(session, "second_factor_requirement", level)
    await session.commit()


async def _enrol(session: AsyncSession, user) -> None:
    """Give the account an authenticator it has proved."""
    session.add(UserTotp(user_id=user.id, confirmed_at=datetime.now(timezone.utc)))
    await session.commit()


async def _member_of_a_guild(session: AsyncSession, **overrides):
    user = await create_user(session, **overrides)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    return user, guild


def _refused(response) -> None:
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "PLATFORM_AUTH_FACTOR_REQUIRED"
    assert "insufficient_user_authentication" in response.headers["WWW-Authenticate"]


# ── Who is asked ───────────────────────────────────────────────────────────


async def test_a_deployment_that_asks_nothing_asks_nothing(
    client: AsyncClient, session: AsyncSession
):
    """The default, and what an upgrade finds."""
    user = await create_user(session)

    answered = await client.get(GUILDS_URL, headers=get_auth_headers(user))

    assert answered.status_code == 200, answered.text


async def test_asking_everyone_reaches_an_ordinary_account(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    await _ask(session, SecondFactorRequirement.everyone)

    _refused(await client.get(GUILDS_URL, headers=get_auth_headers(user)))


async def test_asking_the_platform_rungs_leaves_members_alone(
    client: AsyncClient, session: AsyncSession
):
    """The narrower of the two forms: a member of the platform is not one of
    the people it is about."""
    user = await create_user(session)
    await _ask(session, SecondFactorRequirement.platform_roles)

    answered = await client.get(GUILDS_URL, headers=get_auth_headers(user))

    assert answered.status_code == 200, answered.text


async def test_asking_the_platform_rungs_reaches_support(
    client: AsyncClient, session: AsyncSession
):
    staff = await create_user(session, role=UserRole.support)
    await _ask(session, SecondFactorRequirement.platform_roles)

    _refused(await client.get(GUILDS_URL, headers=get_auth_headers(staff)))


# ── What answers it ────────────────────────────────────────────────────────


async def test_an_account_holding_an_authenticator_is_admitted(
    client: AsyncClient, session: AsyncSession
):
    """Holding one answers the deployment, whatever this session presented:
    the question is about the account."""
    user = await create_user(session)
    await _enrol(session, user)
    await _ask(session, SecondFactorRequirement.everyone)

    answered = await client.get(GUILDS_URL, headers=get_auth_headers(user))

    assert answered.status_code == 200, answered.text


async def test_an_unconfirmed_enrolment_answers_nothing(
    client: AsyncClient, session: AsyncSession
):
    """A row appears when somebody starts enrolling. Until it is confirmed the
    authenticator is not known to produce codes this account accepts, and
    sign-in does not ask for it — so neither does this."""
    user = await create_user(session)
    session.add(UserTotp(user_id=user.id, confirmed_at=None))
    await session.commit()
    await _ask(session, SecondFactorRequirement.everyone)

    _refused(await client.get(GUILDS_URL, headers=get_auth_headers(user)))


async def test_an_account_holding_a_passkey_is_admitted(
    client: AsyncClient, session: AsyncSession
):
    """Either factor answers: the deployment asks for one, not for which."""
    from app.services.auth import passkeys as passkey_service

    user = await create_user(session)
    await passkey_service.store(
        session,
        user_id=user.id,
        registered=passkey_service.RegisteredCredential(
            credential_id=b"credential-bytes",
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
    await _ask(session, SecondFactorRequirement.everyone)

    answered = await client.get(GUILDS_URL, headers=get_auth_headers(user))

    assert answered.status_code == 200, answered.text


async def test_a_session_that_presented_one_is_admitted(
    client: AsyncClient, session: AsyncSession
):
    """An account whose identity provider carries out the second factor holds
    nothing here, and the session says it was used. That answers."""
    user = await create_user(session)
    await _ask(session, SecondFactorRequirement.everyone)
    token = get_auth_token(user, amr=["pwd", "otp", "mfa"])

    answered = await client.get(
        GUILDS_URL, headers={"Authorization": f"Bearer {token}"}
    )

    assert answered.status_code == 200, answered.text


# ── The credentials that cannot present anything ───────────────────────────


async def _api_key_headers(session: AsyncSession, user, secret: str) -> dict[str, str]:
    session.add(
        UserApiKey(
            user_id=user.id,
            name="key",
            token_prefix=secret[:8],
            token_hash=api_keys_service._hash_token(secret),
        )
    )
    await session.commit()
    return {"Authorization": f"Bearer {secret}"}


async def test_a_personal_api_key_waits_for_its_owner(
    client: AsyncClient, session: AsyncSession
):
    """It carries nothing about a sign-in, so it answers by its owner holding
    a factor — refused until they do."""
    user = await create_user(session)
    headers = await _api_key_headers(session, user, "ppk_waiting-for-a-factor")
    await _ask(session, SecondFactorRequirement.everyone)

    _refused(await client.get(GUILDS_URL, headers=headers))


async def test_a_personal_api_key_works_once_its_owner_holds_one(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    headers = await _api_key_headers(session, user, "ppk_owner-holds-a-factor")
    await _ask(session, SecondFactorRequirement.everyone)
    await _enrol(session, user)

    answered = await client.get(GUILDS_URL, headers=headers)

    assert answered.status_code == 200, answered.text


# ── What stays reachable ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        ME_URL,
        "/api/v1/auth/totp",
        "/api/v1/auth/passkeys",
    ],
)
async def test_the_ways_to_meet_it_stay_reachable(
    client: AsyncClient, session: AsyncSession, url: str
):
    """Reading who you are, and the two pages that hand out a factor. Without
    these an account the rule covers could not act on it."""
    user = await create_user(session)
    await _ask(session, SecondFactorRequirement.everyone)

    answered = await client.get(url, headers=get_auth_headers(user))

    assert answered.status_code == 200, answered.text


async def test_enrolling_answers_the_rule_it_was_asked_by(
    client: AsyncClient, session: AsyncSession
):
    """The whole loop, as somebody meets it: refused, enrol, admitted — with
    the session they already had."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    await _ask(session, SecondFactorRequirement.everyone)
    _refused(await client.get(GUILDS_URL, headers=headers))

    begun = await client.post(
        "/api/v1/auth/totp/enroll", headers=headers, json={"current_password": None}
    )
    assert begun.status_code != 401, begun.text

    await _enrol(session, user)
    answered = await client.get(GUILDS_URL, headers=headers)
    assert answered.status_code == 200, answered.text


# ── Guild content, and the socket that serves it ───────────────────────────


async def test_a_community_is_out_of_reach_until_it_is_answered(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    from app.api import deps

    user, guild = await _member_of_a_guild(session)
    await _ask(session, SecondFactorRequirement.everyone)
    url = f"/api/v1/c/{guild.id}/initiatives/"

    _refused(await client.get(url, headers=get_auth_headers(user)))

    # Answered, the request asks the credential stores once: the seam behind
    # the account dependency does not put the question again.
    await _enrol(session, user)
    asked: list[int] = []
    holds = deps._account_holds_factor

    async def counted(account, guild_id):
        asked.append(account.id)
        return await holds(account, guild_id)

    monkeypatch.setattr(deps, "_account_holds_factor", counted)
    answered = await client.get(url, headers=get_auth_headers(user))
    assert answered.status_code == 200, answered.text
    assert asked == [user.id]


async def test_a_socket_is_refused_the_same_way(
    client: AsyncClient, session: AsyncSession
):
    """The sockets resolve their guild through the loader rather than the
    dependency, so the question is asked there too."""
    from app.api.deps import GuildAccessError, establish_guild_access
    from app.services.platform.ws_auth import authenticate_ws_token

    user, guild = await _member_of_a_guild(session)
    await _ask(session, SecondFactorRequirement.everyone)

    resolved = await authenticate_ws_token(get_auth_token(user), session)
    assert resolved is not None
    with pytest.raises(GuildAccessError) as refusal:
        await establish_guild_access(session, resolved, guild.id)
    assert refusal.value.detail == "PLATFORM_AUTH_FACTOR_REQUIRED"


# ── And the database, which decides it for itself ──────────────────────────


async def _database_admits(
    session: AsyncSession, *, platform_role: str, platform_factor: bool
) -> bool:
    """What ``public.platform_factor_satisfied()`` says, given the GUCs a
    request with this standing would have set."""
    verdict = (
        await session.exec(
            text(
                "SELECT set_config('app.platform_role', :prole, true), "
                "set_config('app.platform_factor', :pfac, true), "
                "public.platform_factor_satisfied() AS verdict"
            ),
            params={
                "prole": platform_role,
                "pfac": "true" if platform_factor else "false",
            },
        )
    ).one()
    return bool(verdict.verdict)


@pytest.mark.parametrize(
    ("level", "platform_role", "platform_factor", "admitted"),
    [
        (SecondFactorRequirement.nobody, "member", False, True),
        (SecondFactorRequirement.nobody, "owner", False, True),
        (SecondFactorRequirement.platform_roles, "member", False, True),
        (SecondFactorRequirement.platform_roles, "support", False, False),
        (SecondFactorRequirement.platform_roles, "support", True, True),
        (SecondFactorRequirement.everyone, "member", False, False),
        (SecondFactorRequirement.everyone, "member", True, True),
        # Nothing recorded about the rung is not a member, and nothing
        # recorded about the standing is not answered.
        (SecondFactorRequirement.platform_roles, "", False, False),
        (SecondFactorRequirement.everyone, "", True, True),
    ],
)
async def test_the_database_decides_the_same_rule(
    session: AsyncSession,
    level: SecondFactorRequirement,
    platform_role: str,
    platform_factor: bool,
    admitted: bool,
):
    await _ask(session, level)

    assert (
        await _database_admits(
            session, platform_role=platform_role, platform_factor=platform_factor
        )
        is admitted
    )
