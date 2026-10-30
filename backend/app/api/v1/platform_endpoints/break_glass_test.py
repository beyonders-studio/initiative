"""End-to-end tests for the break-glass path (Phase 3).

``data.bypass`` is the right to self-issue a scoped, time-bound, audited PAM
grant. These tests state what that grant is and what it permits:

* an operator/owner issues one in a single step (created and approved), and the
  row records that they were both the requester and the approver;
* a tier without ``data.bypass`` uses the request->approve flow instead;
* reach into a community comes from the grant, so the same request answers
  differently either side of clicking through;
* the pair it issues — a ``read_write`` content grant and a ``superadmin``
  settings grant — permits editing existing content and reading the
  community's configuration, and is short-lived, non-stacking and capped;
* the second factor it asks of an account that holds one, or that the
  deployment's requirement covers, and the three things that answer it: an
  authenticator code, a recovery code, and an assertion from one of the
  account's own passkeys.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth import sign_in_locks
from app.services.auth import totp as totp_service

from app.core import auth_context
from app.core.login_methods import SecondFactorRequirement
from app.models.platform.guild import Guild, CommunityRole
from app.models.platform.user import UserRole
from app.services.platform import access_grants as access_grants_service
from app.services.platform import rules
from app.testing import (
    Actor,
    assertion_for,
    create_guild,
    create_guild_membership,
    create_passkey,
    stub_assertion,
)

BREAK_GLASS = "/api/v1/access-grants/break-glass"
MINE = "/api/v1/access-grants/"

#: What breaking glass issues, as (purpose, access level) pairs.
THE_PAIR = {("content", "read_write"), ("settings", "superadmin")}


@pytest.fixture
async def outsider(acting_user, session: AsyncSession):
    """An account at ``tier`` plus a community it does not belong to.

    The community's creator is an account of its own, so the caller is a
    stranger to it — which is the position break-glass is about.
    """

    async def _make(tier: str = "operator") -> tuple[Actor, Guild]:
        actor = await acting_user(tier)
        return actor, await create_guild(session)

    return _make


async def _break_glass(
    client: AsyncClient, actor: Actor, guild: Guild, **body
) -> object:
    """Click through, with ``reason`` and any credential the caller supplies."""
    return await client.post(
        BREAK_GLASS,
        json={"community_id": guild.id, "reason": "prod incident #42", **body},
        headers=actor.headers,
    )


async def _live_pair(client: AsyncClient, actor: Actor) -> set[tuple[str, str]]:
    """The (purpose, access level) pairs the caller holds right now."""
    listed = await client.get(MINE, headers=actor.headers)
    assert listed.status_code == 200, listed.text
    return {
        (g["purpose"], g["access_level"])
        for g in listed.json()["items"]
        if g["is_live"]
    }


async def test_break_glass_self_issues_live_grant(client: AsyncClient, outsider):
    """An operator issues a grant in one step: created AND approved, live
    immediately, with requester == approver as the record of who took it."""
    a, guild = await outsider()

    resp = await _break_glass(client, a, guild)

    assert resp.status_code == 201, resp.text
    grant = resp.json()
    assert grant["status"] == "approved"
    assert grant["is_live"] is True
    # Breaking glass is not a dial: write access to the content, and a
    # settings grant alongside it.
    assert grant["access_level"] == "read_write"
    assert grant["expires_at"] is not None
    assert grant["user_id"] == a.user.id
    assert grant["requested_by_id"] == a.user.id
    assert grant["approved_by_id"] == a.user.id  # self-approved = the record


async def test_break_glass_requires_data_bypass(client: AsyncClient, outsider):
    """Support and moderator hold ``access.request`` rather than
    ``data.bypass``, so the request->approve flow is their way in."""
    a, guild = await outsider("support")

    resp = await _break_glass(client, a, guild, reason="no bypass")

    assert resp.status_code == 403, resp.text


async def test_admin_reaches_guild_only_after_clicking_through(
    client: AsyncClient, acting_user, outsider
):
    """THE Phase 3 smoke test: reach into a community comes from the grant, so
    the same request answers 403 before clicking through and 200 after, scoped
    to that one community."""
    a, guild = await outsider()
    host = await acting_user(
        guild_role=CommunityRole.admin, guild=guild, initiative=True
    )

    before = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=a.headers)
    assert before.status_code == 403

    issued = await _break_glass(client, a, guild, reason="investigate")
    assert issued.status_code == 201, issued.text
    assert issued.json()["is_live"] is True

    after = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=a.headers)
    assert after.status_code == 200, after.text
    assert any(i["name"] == host.initiative.name for i in after.json())


async def test_break_glass_reaches_no_further_than_any_other_grant(
    client: AsyncClient, acting_user, outsider
):
    """Breaking glass issues two grants and no special authority.

    The content grant is ``read_write`` and means what it means for support:
    existing content, not authoring and not access management. The settings
    grant is what carries a community's configuration, and it is recorded
    separately so the log says which was exercised.
    """
    a, guild = await outsider()
    host = await acting_user(
        guild_role=CommunityRole.admin, guild=guild, initiative=True, project=True
    )
    target = await acting_user()

    resp = await _break_glass(client, a, guild, reason="full incident response")
    assert resp.status_code == 201, resp.text
    assert resp.json()["access_level"] == "read_write"

    # Both rows are there, each naming what it is for.
    assert await _live_pair(client, a) == THE_PAIR

    # Authoring is not what a content grant is: no new project.
    authored = await client.post(
        f"/api/v1/c/{guild.id}/projects/",
        json={"name": "New Front", "initiative_id": host.initiative.id},
        headers=a.headers,
    )
    assert authored.status_code == 403, authored.text

    # Nor is handing access out.
    shared = await client.put(
        f"/api/v1/c/{guild.id}/projects/{host.project.id}/grants",
        json=[{"user_id": target.user.id, "level": "write"}],
        headers=a.headers,
    )
    assert shared.status_code == 403, shared.text

    # What the settings grant carries: the community's own configuration.
    rules = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings", headers=a.headers
    )
    assert rules.status_code == 200, rules.text


async def test_break_glass_already_member_rejected(
    client: AsyncClient, session: AsyncSession, outsider
):
    """A member of the community already has standing access, so break-glass is
    rejected as redundant."""
    a, guild = await outsider()
    await create_guild_membership(
        session, user=a.user, guild=guild, role=CommunityRole.member
    )

    resp = await _break_glass(client, a, guild, reason="already in")

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_ALREADY_MEMBER"


async def test_break_glass_duration_capped(client: AsyncClient, outsider):
    """A self-approved grant is capped at the (short) break-glass ceiling,
    below the role's request->approve maximum. 24h is inside an operator's
    request->approve cap and over break-glass's 4h."""
    a, guild = await outsider()

    resp = await _break_glass(
        client, a, guild, reason="too long", requested_duration_minutes=1440
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


async def test_breaking_glass_again_supersedes_rather_than_stacking(
    client: AsyncClient, outsider
):
    """Re-issuing is how the window is extended, so a second one replaces the
    first rather than being refused. Nothing stacks: the earlier pair is
    revoked, and the log keeps it."""
    a, guild = await outsider()

    first = await _break_glass(client, a, guild, reason="first")
    assert first.status_code == 201, first.text
    second = await _break_glass(client, a, guild, reason="second")
    assert second.status_code == 201, second.text

    assert await _live_pair(client, a) == THE_PAIR
    listed = await client.get(MINE, headers=a.headers)
    assert sum(1 for g in listed.json()["items"] if g["status"] == "revoked") == 2


async def test_break_glass_denies_a_pending_request_before_issuing_the_pair(
    client: AsyncClient, outsider
):
    """Clicking through settles whatever the same person had asked for: the
    pending request is decided, and the pair is what they hold after."""
    a, guild = await outsider()

    requested = await client.post(
        "/api/v1/access-grants/",
        headers=a.headers,
        json={
            "community_id": guild.id,
            "access_level": "read",
            "reason": "ordinary content work",
        },
    )
    assert requested.status_code == 201, requested.text

    issued = await _break_glass(client, a, guild, reason="urgent content repair")
    assert issued.status_code == 201, issued.text

    listed = await client.get(MINE, headers=a.headers)
    prior = next(g for g in listed.json()["items"] if g["id"] == requested.json()["id"])
    assert prior["status"] == "denied"
    assert await _live_pair(client, a) == THE_PAIR


# ---------------------------------------------------------------------------
# The second factor (D9)
#
# Breaking glass carries the account's own factor when the account holds one,
# or when the deployment requires one of its rung. What other accounts hold
# asks nothing of it.
# ---------------------------------------------------------------------------


def _next_code(secret: str) -> str:
    """The code for the interval after this one.

    Confirming an enrolment takes the interval its code came from, so breaking
    glass in the same thirty seconds cannot present that code again — which is
    the rule working, and the reason the code proves presence at all. One
    interval ahead is inside the drift a clock is allowed.
    """
    import pyotp

    at = datetime.now(timezone.utc) + timedelta(seconds=totp_service.TOTP_PERIOD)
    return pyotp.TOTP(secret).at(at)


async def _enrol_factor(
    client: AsyncClient,
    session: AsyncSession,
    actor: Actor,
    password: str = "testpassword123",
) -> tuple[str, list[str]]:
    """Give ``actor`` a confirmed factor, returning (secret, recovery codes)."""
    import pyotp

    started = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": password},
        headers=actor.headers,
    )
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=actor.headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    await session.refresh(actor.user)
    return secret, confirmed.json()["codes"]


@pytest.mark.parametrize("colleague_factor", ["authenticator", "passkey"])
async def test_a_colleagues_factor_asks_nothing_of_an_account_without_one(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    outsider,
    colleague_factor,
):
    """The ask is the caller's own: another ``data.bypass`` holder setting one
    up does not ask anything of an account that has not."""
    a, guild = await outsider()
    colleague = await acting_user("operator")
    if colleague_factor == "authenticator":
        await _enrol_factor(client, session, colleague)
    else:
        await create_passkey(session, colleague.user)

    resp = await _break_glass(client, a, guild, reason="incident")

    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize(
    "level,signed_in_with,asked",
    [
        (SecondFactorRequirement.nobody, frozenset(), False),
        (SecondFactorRequirement.platform_roles, frozenset(), True),
        (SecondFactorRequirement.everyone, frozenset(), True),
        (SecondFactorRequirement.everyone, frozenset({"mfa"}), False),
    ],
)
async def test_the_deployments_requirement_asks_an_account_without_one(
    session: AsyncSession, acting_user, level, signed_in_with, asked
):
    """Where the deployment requires a factor of the caller's rung, breaking
    glass asks for one even of an account that holds none, and the refusal
    sends it to enrol — unless its identity provider carried the factor at
    sign-in, which answers the deployment's requirement everywhere else too.
    Asked of the rule directly: the deployment's own gate turns an account
    with neither away sooner."""
    a = await acting_user("operator")
    await rules.put(session, "second_factor_requirement", level)
    await session.commit()

    auth_context.record(session_amr=signed_in_with)
    try:
        demanded = await access_grants_service.demands_second_factor(
            session, actor=a.user
        )
    finally:
        auth_context.reset()
    assert demanded is asked


@pytest.mark.parametrize(
    "credential,expected,detail",
    [
        pytest.param(
            None, 401, "ACCESS_GRANT_SECOND_FACTOR_REQUIRED", id="nothing-presented"
        ),
        pytest.param("wrong", 400, "TOTP_INVALID", id="a-code-that-is-not-theirs"),
        pytest.param("code", 201, None, id="the-authenticator-code"),
        # The phone is the thing most likely to be missing in the hour somebody
        # needs this, so the set kept for that answers it as well.
        pytest.param("recovery", 201, None, id="a-recovery-code"),
    ],
)
async def test_what_an_enrolled_holder_presents_to_break_glass(
    client: AsyncClient,
    session: AsyncSession,
    outsider,
    credential,
    expected,
    detail,
):
    """An account that holds a factor is asked for it, and its own factor is
    what answers. Wrong codes count against the account as they do at sign-in,
    so enough of them turn the right one away too."""
    a, guild = await outsider()
    secret, codes = await _enrol_factor(client, session, a)
    body = {
        None: {},
        "wrong": {"code": "000000"},
        "code": {"code": _next_code(secret)},
        "recovery": {"recovery_code": codes[0]},
    }[credential]

    resp = await _break_glass(client, a, guild, reason="incident", **body)

    assert resp.status_code == expected, resp.text
    if detail is not None:
        assert resp.json()["detail"] == detail
    else:
        assert resp.json()["status"] == "approved"

    if credential == "wrong":
        for _ in range(sign_in_locks.LOCK_AFTER_FAILURES - 1):
            again = await _break_glass(client, a, guild, reason="incident", **body)
            assert again.status_code == 400, again.text
        locked = await _break_glass(
            client, a, guild, reason="incident", code=_next_code(secret)
        )
        assert locked.status_code == 429, locked.text
        assert locked.json()["detail"] == "SIGN_IN_LOCKED"


async def test_withdrawing_the_authenticator_stops_it_being_asked_for(
    client: AsyncClient, session: AsyncSession, acting_user, outsider
):
    """Only a method the deployment still offers is asked for."""
    from app.core.login_methods import LoginMethod
    from app.services.platform import auth_posture

    a, guild = await outsider()
    owner = await acting_user("owner")
    await _enrol_factor(client, session, a)

    # While it is offered, the holder is asked for its code.
    asked = await _break_glass(client, a, guild, reason="incident")
    assert asked.status_code == 401, asked.text

    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner.user),
        {"login_methods": frozenset([LoginMethod.password, LoginMethod.sso])},
    )

    resp = await _break_glass(client, a, guild, reason="incident")
    assert resp.status_code == 201, resp.text


async def test_the_form_is_told_what_it_will_be_asked_for(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user("operator")
    window = access_grants_service.break_glass_max_minutes(UserRole.operator)

    before = await client.get(BREAK_GLASS, headers=a.headers)
    assert before.status_code == 200, before.text
    assert before.json() == {
        "second_factor_required": False,
        "max_duration_minutes": window,
        "totp_enrolled": False,
        "passkey_enrolled": False,
    }

    await _enrol_factor(client, session, a)

    after = await client.get(BREAK_GLASS, headers=a.headers)
    assert after.json() == {
        "second_factor_required": True,
        "max_duration_minutes": window,
        "totp_enrolled": True,
        "passkey_enrolled": False,
    }

    # And the other thing that answers, so the form knows it can offer it.
    await create_passkey(session, a.user)
    with_a_key = await client.get(BREAK_GLASS, headers=a.headers)
    assert with_a_key.json() == {
        "second_factor_required": True,
        "max_duration_minutes": window,
        "totp_enrolled": True,
        "passkey_enrolled": True,
    }


# --- and the key that answers it -------------------------------------------

PASSKEY_BEGIN = f"{BREAK_GLASS}/passkey"


async def _present_a_key(
    client: AsyncClient, actor: Actor, *, credential_id: str = "credential-one"
) -> dict:
    """Begin the ceremony this request will answer, and shape the answer.

    The challenge comes back inside the options the browser would be handed,
    and goes back inside the client data it would sign — so the assertion is
    held against a challenge issued for breaking glass, and for this account.
    """
    begun = await client.post(PASSKEY_BEGIN, headers=actor.headers)
    assert begun.status_code == 200, begun.text
    challenge = begun.json()["options"]["challenge"]
    return assertion_for(challenge, credential_id=credential_id)


async def test_a_holder_with_only_a_key_is_not_sent_to_enrol_an_authenticator(
    client: AsyncClient, session: AsyncSession, outsider, monkeypatch
):
    """A passkey is a factor the account holds, so holding one is what the ask
    is answered from — an authenticator app is not a second thing to acquire."""
    stub_assertion(monkeypatch)
    a, guild = await outsider()
    await create_passkey(session, a.user)

    # Nothing presented is still refused, but for the right reason: it asks
    # rather than sending them away to enrol.
    empty = await _break_glass(client, a, guild, reason="incident")
    assert empty.status_code == 401, empty.text
    assert empty.json()["detail"] == "ACCESS_GRANT_SECOND_FACTOR_REQUIRED"

    answered = await _break_glass(
        client, a, guild, reason="incident", passkey=await _present_a_key(client, a)
    )
    assert answered.status_code == 201, answered.text
    assert answered.json()["status"] == "approved"


async def test_an_assertion_answers_one_request(
    client: AsyncClient, session: AsyncSession, outsider, monkeypatch
):
    """The challenge is spent by the request that carries it, so the same
    assertion does not break glass a second time."""
    stub_assertion(monkeypatch)
    a, guild = await outsider()
    await create_passkey(session, a.user)

    presented = await _present_a_key(client, a)
    first = await _break_glass(client, a, guild, reason="incident", passkey=presented)
    assert first.status_code == 201, first.text

    _, another = await outsider()
    again = await _break_glass(client, a, another, reason="incident", passkey=presented)
    assert again.status_code == 400, again.text
    assert again.json()["detail"] == "ACCESS_GRANT_PASSKEY_INVALID"


async def test_somebody_elses_key_does_not_answer(
    client: AsyncClient, session: AsyncSession, acting_user, outsider, monkeypatch
):
    """A credential that verifies is not the same as this account's."""
    stub_assertion(monkeypatch)
    a, guild = await outsider()
    await create_passkey(session, a.user)
    colleague = await acting_user("operator")
    await create_passkey(session, colleague.user, credential_id="their-key")

    # The challenge is this account's; the key answering it is not.
    refused = await _break_glass(
        client,
        a,
        guild,
        reason="incident",
        passkey=await _present_a_key(client, a, credential_id="their-key"),
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "ACCESS_GRANT_PASSKEY_INVALID"


async def test_a_step_up_challenge_does_not_break_glass(
    client: AsyncClient, session: AsyncSession, outsider, monkeypatch
):
    """The purposes are kept apart: what a session step-up issued answers for
    the session, and breaking glass asks for a proof of its own."""
    stub_assertion(monkeypatch)
    a, guild = await outsider()
    await create_passkey(session, a.user)

    begun = await client.post("/api/v1/auth/step-up/passkey/begin", headers=a.headers)
    assert begun.status_code == 200, begun.text
    for_the_session = assertion_for(begun.json()["options"]["challenge"])

    refused = await _break_glass(
        client, a, guild, reason="incident", passkey=for_the_session
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "ACCESS_GRANT_PASSKEY_INVALID"
