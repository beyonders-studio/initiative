"""Tests for OIDC identity resolution.

Pins the resolution ladder — (provider, subject) link first, verified-email
match surfaced but never written, JIT last and gated — and that refusals are
outcomes, not exceptions.
"""

from __future__ import annotations

import secrets

from sqlmodel import select

from app.services.platform import rules
from app.core.encryption import hash_email
from app.core.login_methods import LoginMethod
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_email import UserEmail
from app.services.auth import addresses
from app.services.auth.identity import (
    IdentityResolution,
    ResolutionOutcome,
    link_identity,
    resolve_oidc_identity,
    stranded_between,
)
from app.testing import create_user


#: What a deployment offering everything it could permits, and the same set
#: with one method withdrawn. The counts take this explicitly, so a test says
#: which posture it is asking about rather than writing the settings row.
#: Every way in a deployment could offer.
EVERYTHING = frozenset(LoginMethod)

#: Everything an account has to acquire — a password, a link to a provider, a
#: registered key. The emailed code is left out because it asks nothing of the
#: account: every account holding an address can use it, so with it permitted
#: no account's only way in is ever one of the others. The questions below are
#: about the others, so they are asked in the posture where that is a question.
#: :func:`test_an_address_is_a_way_in_on_its_own` covers the code itself.
CREDENTIALS = EVERYTHING - {LoginMethod.email_otp}


def _without(*methods: LoginMethod) -> frozenset[LoginMethod]:
    return CREDENTIALS - set(methods)


async def _only_way_in_count(
    session, method: LoginMethod, *, permitted: frozenset[LoginMethod]
) -> int:
    """How many accounts can begin a session only by ``method``, on a
    deployment offering ``permitted`` — what withdrawing it would strand."""
    return await stranded_between(
        session, current=permitted, requested=permitted - {method}
    )


async def _create_provider(session, *, allow_jit: bool = True) -> AuthProvider:
    provider = AuthProvider(
        slug=f"idp-{secrets.token_hex(4)}",
        display_name="Test IdP",
        kind=AuthProviderKind.oidc.value,
        enabled=True,
        issuer="https://idp.example.com",
        client_id="client-123",
        allow_jit=allow_jit,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


async def _address(session, user_id: int) -> UserEmail | None:
    """The account's primary address row — where an address lives."""
    return (
        await session.exec(
            select(UserEmail).where(UserEmail.user_id == user_id, UserEmail.is_primary)
        )
    ).one_or_none()


async def _resolve(session, provider, **overrides) -> IdentityResolution:
    kwargs = {
        "subject": "sub-1",
        "email": "alice@example.com",
        "email_verified": True,
    }
    kwargs.update(overrides)
    return await resolve_oidc_identity(session, provider=provider, **kwargs)


async def _identities_for(session, provider) -> list[FederatedIdentity]:
    return list(
        (
            await session.exec(
                select(FederatedIdentity).where(
                    FederatedIdentity.provider_id == provider.id
                )
            )
        ).all()
    )


# --- linked -------------------------------------------------------------------


async def test_existing_link_resolves_to_user(session):
    provider = await _create_provider(session)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider, subject="sub-1", email_verified=True
    )

    result = await _resolve(session, provider)
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.user.id == user.id
    assert result.identity.last_login_at is not None
    # The returned user must be usable past its PK: the wiring endpoint reads
    # user.status for the active/deactivated gate. Sessions are expire_on_commit
    # =False (db/session.py + the fixture), so the SELECT-loaded user stays
    # populated after the identity commit — no lazy IO, no MissingGreenlet. This
    # access would raise if that ever regressed to expire-on-commit.
    assert result.user.status == UserStatus.active
    assert result.user.id == user.id


async def test_link_is_scoped_to_its_provider(session):
    """The same subject at a different provider is a different identity."""
    provider_a = await _create_provider(session)
    provider_b = await _create_provider(session, allow_jit=False)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider_a, subject="sub-1", email_verified=True
    )

    result = await _resolve(
        session, provider_b, email="nobody@example.com", subject="sub-1"
    )
    assert result.outcome is ResolutionOutcome.JIT_DISABLED


async def test_linked_login_refreshes_email_verified_snapshot(session):
    provider = await _create_provider(session)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider, subject="sub-1", email_verified=False
    )

    result = await _resolve(session, provider, email_verified=True)
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.identity.email_verified is True


# --- email match (no link) ------------------------------------------------------


async def test_verified_email_match_is_surfaced_but_not_linked(session):
    """An unlinked account matched by verified email is the caller's policy
    decision — resolution itself must not write a link."""
    provider = await _create_provider(session)
    user = await create_user(session, email="alice@example.com")

    result = await _resolve(session, provider, email="alice@example.com")
    assert result.outcome is ResolutionOutcome.EMAIL_MATCH
    assert result.user.id == user.id
    assert result.identity is None
    assert await _identities_for(session, provider) == []


async def test_unverified_email_match_is_refused(session):
    provider = await _create_provider(session)
    await create_user(session, email="victim@example.com")

    result = await _resolve(
        session, provider, email="victim@example.com", email_verified=False
    )
    assert result.outcome is ResolutionOutcome.EMAIL_UNVERIFIED
    assert await _identities_for(session, provider) == []


# --- JIT provisioning -----------------------------------------------------------


async def test_unknown_user_is_provisioned_and_linked(session):
    provider = await _create_provider(session)

    result = await _resolve(session, provider, email="new@example.com")
    assert result.outcome is ResolutionOutcome.PROVISIONED
    user = result.user
    assert await addresses.holds_address(
        session, user_id=user.id, email="new@example.com"
    )
    assert user.role == UserRole.member
    assert user.status == UserStatus.active
    assert (await _address(session, user.id)).verified_at is not None
    # SSO-only: no password is set — a NULL hash never verifies, so this
    # account signs in exclusively through its provider.
    assert user.hashed_password is None
    assert result.identity.subject == "sub-1"

    # The very next login resolves via the link.
    again = await _resolve(session, provider, email="new@example.com")
    assert again.outcome is ResolutionOutcome.LINKED
    assert again.user.id == user.id


async def test_provisioned_user_with_unverified_email_not_marked_verified(session):
    provider = await _create_provider(session)
    result = await _resolve(
        session, provider, email="fresh@example.com", email_verified=False
    )
    assert result.outcome is ResolutionOutcome.PROVISIONED
    assert (await _address(session, result.user.id)).verified_at is None


async def test_missing_email_claim_uses_synthetic_address(session):
    provider = await _create_provider(session)
    result = await _resolve(session, provider, email=None, subject="opaque-7")
    assert result.outcome is ResolutionOutcome.PROVISIONED
    row = await _address(session, result.user.id)
    assert row.email_hash == hash_email("opaque-7@oidc.local")
    # A synthetic address is not a mailbox; it is never marked verified.
    assert row.verified_at is None


async def test_jit_disabled_provider_refuses_unknown_user(session):
    provider = await _create_provider(session, allow_jit=False)
    result = await _resolve(session, provider, email="stranger@example.com")
    assert result.outcome is ResolutionOutcome.JIT_DISABLED
    assert result.user is None
    assert await _identities_for(session, provider) == []


async def test_provision_recovers_from_subject_race_without_orphan(session):
    """Case (a): a concurrent login committed our (provider, subject) first.
    _provision must resolve to the winner (LINKED) and leave no orphaned user.
    (The winner is created via a prior commit, which survives the service's
    rollback; _provision is called directly since the top-level resolve would
    short-circuit to LINKED before ever provisioning.)"""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="winner@example.com")
    await link_identity(
        session, user=winner, provider=provider, subject="sub-1", email_verified=True
    )

    result = await _provision(
        session,
        provider=provider,
        subject="sub-1",
        email="loser@example.com",
        email_verified=True,
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.user.id == winner.id
    # Our uncommitted user was rolled back — no orphan.
    loser = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("loser@example.com"))
        )
    ).one_or_none()
    assert loser is None


async def test_provision_recovers_from_email_race_as_email_match(session):
    """Case (b): a *different* subject with the same email won the email_hash
    unique race. The loser must surface EMAIL_MATCH (never a silent link), not
    re-raise a 500."""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="shared@example.com")

    result = await _provision(
        session,
        provider=provider,
        subject="sub-new",
        email="shared@example.com",
        email_verified=True,
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.EMAIL_MATCH
    assert result.user.id == winner.id
    assert await _identities_for(session, provider) == []  # no link written


async def test_provision_email_race_unverified_is_refused(session):
    """Case (b) with an unverified asserted email → EMAIL_UNVERIFIED, mirroring
    the non-raced unverified-email refusal."""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="victim@example.com")

    result = await _provision(
        session,
        provider=provider,
        subject="sub-new",
        email="victim@example.com",
        email_verified=False,
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.EMAIL_UNVERIFIED
    assert result.user.id == winner.id
    assert await _identities_for(session, provider) == []


async def test_closed_registration_refuses_unknown_user(session, monkeypatch):
    provider = await _create_provider(session)
    await create_user(session)  # instance is not empty → no bootstrap exception
    await rules.put(session, "public_registration_enabled", False)
    await session.commit()

    result = await _resolve(session, provider, email="stranger@example.com")
    assert result.outcome is ResolutionOutcome.REGISTRATION_DISABLED
    assert await _identities_for(session, provider) == []


async def test_a_pkce_provider_counts_as_a_way_in(session):
    """A stored client secret is the platform row's own requirement, so a
    provider beside it answers logins without one — and the counts deciding
    whether single sign-on can be withdrawn include whoever arrives that way."""
    from app.testing.factories import (
        create_auth_provider,
        create_federated_identity,
        create_guild,
        create_user,
    )

    # Makes its own creator, who holds a password — the baseline below.
    await create_guild(session)
    provider = await create_auth_provider(session, slug="pkce")  # no client secret
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    # Their only way in is that provider, so withdrawing SSO concerns them.
    assert (
        await _only_way_in_count(session, LoginMethod.sso, permitted=CREDENTIALS) == 1
    )

    # And somebody holding a password *and* that provider is not an account the
    # password is holding up. Measured as a delta: creating the guild above
    # made its own creator, who holds a password and no identity.
    baseline = await _only_way_in_count(
        session, LoginMethod.password, permitted=CREDENTIALS
    )
    holder = await create_user(session)
    await create_federated_identity(session, holder, provider=provider)
    assert (
        await _only_way_in_count(session, LoginMethod.password, permitted=CREDENTIALS)
        == baseline
    )


# ---------------------------------------------------------------------------
# A passkey is a way in, while the deployment permits one
# ---------------------------------------------------------------------------


async def _store_passkey(session, user) -> None:
    from app.services.auth import passkeys as passkey_service

    await passkey_service.store(
        session,
        user_id=user.id,
        registered=passkey_service.RegisteredCredential(
            credential_id=f"count-{user.id}".encode(),
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


async def test_a_password_holder_with_a_passkey_is_not_password_only(session):
    """Withdrawing the password leaves them their credential — until the
    deployment stops permitting one, when the password is again all they have."""

    baseline = await _only_way_in_count(
        session, LoginMethod.password, permitted=CREDENTIALS
    )
    holder = await create_user(session)
    assert (
        await _only_way_in_count(session, LoginMethod.password, permitted=CREDENTIALS)
        == baseline + 1
    )

    await _store_passkey(session, holder)
    assert (
        await _only_way_in_count(session, LoginMethod.password, permitted=CREDENTIALS)
        == baseline
    )

    no_passkeys = _without(LoginMethod.passkey)
    assert (
        await _only_way_in_count(session, LoginMethod.password, permitted=no_passkeys)
        == baseline + 1
    )


async def test_a_passkey_keeps_a_federated_account_off_the_sso_count(session):
    from app.testing.factories import create_auth_provider, create_federated_identity

    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)
    assert (
        await _only_way_in_count(session, LoginMethod.sso, permitted=CREDENTIALS) == 1
    )

    await _store_passkey(session, member)
    assert (
        await _only_way_in_count(session, LoginMethod.sso, permitted=CREDENTIALS) == 0
    )

    no_passkeys = _without(LoginMethod.passkey)
    assert (
        await _only_way_in_count(session, LoginMethod.sso, permitted=no_passkeys) == 1
    )


async def test_a_passkey_survives_the_provider_it_signed_up_through(session):
    """Deleting a provider takes its links with it. An account holding a
    credential of its own is not left without one."""
    from app.services.auth.identity import sole_credential_user_count
    from app.testing.factories import create_auth_provider, create_federated_identity

    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)
    assert (
        await sole_credential_user_count(
            session, provider_id=provider.id, permitted=CREDENTIALS
        )
        == 1
    )

    await _store_passkey(session, member)
    assert (
        await sole_credential_user_count(
            session, provider_id=provider.id, permitted=CREDENTIALS
        )
        == 0
    )

    assert (
        await sole_credential_user_count(
            session, provider_id=provider.id, permitted=_without(LoginMethod.passkey)
        )
        == 1
    )


async def test_an_account_whose_only_way_in_is_a_passkey_is_counted(session):
    """What withdrawing the method would leave stranded."""

    assert (
        await _only_way_in_count(session, LoginMethod.passkey, permitted=CREDENTIALS)
        == 0
    )

    holder = await create_user(session, hashed_password=None)
    await _store_passkey(session, holder)
    assert (
        await _only_way_in_count(session, LoginMethod.passkey, permitted=CREDENTIALS)
        == 1
    )

    # A password beside it is another way in, so they are not.
    beside = await create_user(session)
    await _store_passkey(session, beside)
    assert (
        await _only_way_in_count(session, LoginMethod.passkey, permitted=CREDENTIALS)
        == 1
    )

    no_passkeys = _without(LoginMethod.passkey)
    assert (
        await _only_way_in_count(session, LoginMethod.passkey, permitted=no_passkeys)
        == 0
    )


async def test_a_federated_account_with_a_passkey_is_not_passkey_only(session):
    from app.testing.factories import create_auth_provider, create_federated_identity

    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)
    await _store_passkey(session, member)

    assert (
        await _only_way_in_count(session, LoginMethod.passkey, permitted=CREDENTIALS)
        == 0
    )


async def test_a_method_the_deployment_does_not_offer_strands_nobody(session):
    """A credential whose method is not in the permitted set opens nothing, so
    withdrawing that method takes nothing away from anybody holding one."""
    from app.services.auth.identity import (
        sole_credential_user_count,
    )
    from app.testing.factories import create_auth_provider, create_federated_identity

    provider = await create_auth_provider(session, slug="corp")
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)
    holder = await create_user(session, hashed_password=None)
    await _store_passkey(session, holder)
    await create_user(session)  # holds a password and nothing else

    assert (
        await _only_way_in_count(
            session, LoginMethod.password, permitted=_without(LoginMethod.password)
        )
        == 0
    )
    assert (
        await _only_way_in_count(
            session, LoginMethod.sso, permitted=_without(LoginMethod.sso)
        )
        == 0
    )
    assert (
        await _only_way_in_count(
            session, LoginMethod.passkey, permitted=_without(LoginMethod.passkey)
        )
        == 0
    )
    assert (
        await sole_credential_user_count(
            session, provider_id=provider.id, permitted=_without(LoginMethod.sso)
        )
        == 0
    )


async def test_two_ways_in_withdrawn_together_strand_the_account(session):
    """A password and a credential are each a way in while the other is still
    offered, so the account is stranded by the pair going and by neither alone.
    Counting one method at a time cannot say that; asking about both sets can."""
    from app.services.auth.identity import stranded_between

    holder = await create_user(session)
    await _store_passkey(session, holder)

    assert (
        await stranded_between(
            session, current=CREDENTIALS, requested=_without(LoginMethod.password)
        )
        == 0
    )
    assert (
        await stranded_between(
            session, current=CREDENTIALS, requested=_without(LoginMethod.passkey)
        )
        == 0
    )
    assert (
        await stranded_between(
            session,
            current=CREDENTIALS,
            requested=_without(LoginMethod.password, LoginMethod.passkey),
        )
        == 1
    )


# ---------------------------------------------------------------------------
# Which ways in an account has today
# ---------------------------------------------------------------------------


async def _withdraw_passkeys(session) -> None:
    """Leave the deployment permitting the other three."""

    await rules.put(
        session,
        "login_methods",
        frozenset({LoginMethod.password, LoginMethod.sso, LoginMethod.totp}),
    )
    await session.commit()


async def test_ways_in_reads_the_account_and_the_deployment(session):
    """Both halves decide it: what the account holds, and what is permitted."""
    from app.core.login_methods import LoginMethod
    from app.services.auth.identity import ways_in
    from app.testing.factories import create_auth_provider, create_federated_identity

    holder = await create_user(session)
    assert await ways_in(session, user_id=holder.id) == frozenset(
        {LoginMethod.password}
    )

    await _store_passkey(session, holder)
    assert await ways_in(session, user_id=holder.id) == frozenset(
        {LoginMethod.password, LoginMethod.passkey}
    )

    provider = await create_auth_provider(session, slug="corp")
    await create_federated_identity(session, holder, provider=provider)
    assert await ways_in(session, user_id=holder.id) == frozenset(
        {LoginMethod.password, LoginMethod.passkey, LoginMethod.sso}
    )

    # Withdrawn, the credential the account still holds opens nothing.
    await _withdraw_passkeys(session)
    assert await ways_in(session, user_id=holder.id) == frozenset(
        {LoginMethod.password, LoginMethod.sso}
    )


async def test_an_account_holding_nothing_has_no_way_in(session):
    from app.core.login_methods import LoginMethod
    from app.services.auth.identity import ways_in

    stranded = await create_user(session, hashed_password=None)
    assert await ways_in(session, user_id=stranded.id) == frozenset()

    await _store_passkey(session, stranded)
    assert await ways_in(session, user_id=stranded.id) == frozenset(
        {LoginMethod.passkey}
    )


async def _permit_the_emailed_code(session) -> None:
    """A deployment that offers it alongside the rest."""

    await rules.put(
        session,
        "login_methods",
        frozenset(
            {
                LoginMethod.password,
                LoginMethod.sso,
                LoginMethod.totp,
                LoginMethod.passkey,
                LoginMethod.email_otp,
            }
        ),
    )
    await session.commit()


async def test_an_address_is_a_way_in_on_its_own(session):
    """The emailed code asks nothing of the account beyond an address, so an
    account holding no other credential still has a way in once it is
    permitted — and loses it when it is withdrawn."""
    from app.core.login_methods import LoginMethod
    from app.services.auth.identity import stranded_between, ways_in

    holder = await create_user(session, hashed_password=None)
    assert await ways_in(session, user_id=holder.id) == frozenset()

    await _permit_the_emailed_code(session)
    assert await ways_in(session, user_id=holder.id) == frozenset(
        {LoginMethod.email_otp}
    )

    assert (
        await stranded_between(
            session,
            current=EVERYTHING,
            requested=EVERYTHING - {LoginMethod.email_otp},
        )
        == 1
    )
