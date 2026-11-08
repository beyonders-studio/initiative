"""Registering a WebAuthn credential, and answering with one.

The ceremony is the library's; what lives here is everything around it — which
relying party this deployment is, what a credential row holds, and the rules
about when one may be made or used.

One thing is deliberately *not* here: nothing in this module opens a session.
It reports what a ceremony proved and the caller decides what that is worth.

Every ceremony requires user verification, registration and sign-in alike, so
a credential this deployment holds proves the person as well as the device.
``user_verified`` stays on the row because it records what the ceremony
reported rather than what was asked for.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import webauthn
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core import native_apps
from app.core.clock import utcnow
from app.models.platform.auth_challenge import AuthChallenge
from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey
from app.services.auth import challenges as challenge_service
from app.services.auth.challenges import ChallengePurpose
from app.services.auth.oidc.flow_state import s256

logger = logging.getLogger(__name__)

#: How long a ceremony's challenge stands. The browser prompt is a few seconds
#: of work; a minute is the library's own default and plenty.
CEREMONY_TIMEOUT_MS = 60_000

#: The most credentials one account may register. High enough that nobody
#: bumps it — a phone, a laptop, two hardware keys and room to spare — and low
#: enough that the allow-list sent to a browser stays small.
MAX_PASSKEYS_PER_USER = 20

MAX_NAME_LENGTH = 64

#: The ways of naming the machine itself. A browser treats all three as a
#: secure context, so a deployment addressed by one is an ordinary development
#: setup rather than an address passkeys cannot use.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class PasskeyLimitReached(Exception):
    """The account already has the maximum number of credentials."""


def relying_party_id() -> str:
    """The domain this deployment's credentials belong to.

    A passkey is bound to it, which is the property that makes it worth having
    and also the thing to be careful with: it is derived from ``APP_URL``, so a
    deployment that moves domain is a deployment whose existing credentials no
    longer answer. Every row records the value it was made under so that can be
    said plainly rather than surfacing as a signature that will not verify.
    """
    from app.core.config import settings

    host = urlsplit(settings.APP_URL.strip()).hostname
    if not host:
        raise RuntimeError("APP_URL names no host, so no relying party can be derived")
    return host


def expected_origin() -> str:
    """The origin a ceremony must have come from — scheme, host and port."""
    from app.core.config import settings

    origin = settings.app_origin
    if origin is None:
        raise RuntimeError("APP_URL is not a whole URL, so no origin can be derived")
    return origin


def expected_origins() -> list[str]:
    """Every origin a ceremony may have come from: the deployment's own
    address, and each of the project's Android apps this image names in its
    asset links, which report their signing certificate instead."""
    return [expected_origin(), *native_apps.android_origins()]


def relying_party_name() -> str:
    """What the browser prompt calls this deployment."""
    return relying_party_id()


def site_refusal() -> str | None:
    """Why this deployment's address cannot carry passkeys, or ``None``.

    A credential is bound to a named host reached over https. ``"no_host"``
    says ``APP_URL`` names no host at all; ``"ip_host"`` says it names an
    address rather than a domain; ``"insecure_origin"`` says it is plain http
    somewhere other than the machine itself. All three are properties of the
    deployment's address, so they are answered before a ceremony is begun
    rather than by the browser afterwards — and a caller that has one of them
    never reaches :func:`relying_party_id`, which has no answer to give.
    """
    from app.core.config import settings

    parts = urlsplit(settings.APP_URL.strip())
    host = parts.hostname
    if not host:
        return "no_host"
    # The machine itself is a development address, however it is spelled, so
    # loopback is settled before the address-rather-than-domain rule.
    if host.lower() in _LOCAL_HOSTS:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "ip_host"
    if parts.scheme.lower() == "http":
        return "insecure_origin"
    return None


@dataclass(frozen=True)
class Ceremony:
    """Options for the browser, and the challenge they must come back with."""

    options: dict[str, Any]
    challenge: bytes


@dataclass(frozen=True)
class RegisteredCredential:
    """What a finished registration proved, before it is anybody's."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str | None
    user_verified: bool
    backed_up: bool
    transports: list[str]


async def list_for_user(session: AsyncSession, *, user_id: int) -> list[UserPasskey]:
    rows = await session.exec(
        select(UserPasskey)
        .where(UserPasskey.user_id == user_id)
        .order_by(UserPasskey.created_at)
    )
    return list(rows.all())


async def count_for_user(session: AsyncSession, *, user_id: int) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(UserPasskey)
            .where(UserPasskey.user_id == user_id)
        )
    ).one()


async def begin_registration(
    session: AsyncSession, *, user_id: int, account_name: str, display_name: str
) -> Ceremony:
    """Options for making a new credential on this account.

    The credentials the account already holds go out as ``excludeCredentials``,
    so an authenticator that already has one for this deployment says so rather
    than quietly making a second.
    """
    existing = await list_for_user(session, user_id=user_id)
    if len(existing) >= MAX_PASSKEYS_PER_USER:
        raise PasskeyLimitReached
    options = webauthn.generate_registration_options(
        rp_id=relying_party_id(),
        rp_name=relying_party_name(),
        user_id=str(user_id).encode(),
        user_name=account_name,
        user_display_name=display_name,
        timeout=CEREMONY_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Discoverable, so signing in can start from the key rather than
            # from a typed address — which is the whole shape of the sign-in
            # this is for.
            resident_key=ResidentKeyRequirement.PREFERRED,
            # Required: a credential registered here proves the person — a
            # PIN, a fingerprint, a face — as well as the device, which is
            # what makes signing in with one a multi-factor authentication and
            # why no code is asked for afterwards. The row still records what
            # the ceremony reported.
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=row.credential_id) for row in existing
        ],
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


def begin_sign_up(*, account_name: str, display_name: str) -> Ceremony:
    """Options for the credential a brand-new account will sign in with.

    The same ceremony as :func:`begin_registration`, for the one case where
    there is no account yet: nothing to exclude, because the account holds
    nothing, and a handle drawn here rather than an account id. Nothing ever
    reads the handle back — a credential is found by its own id — so what it
    has to be is unique and not somebody's address, which is what the
    authenticator would otherwise file this deployment's entry under twice.
    """
    options = webauthn.generate_registration_options(
        rp_id=relying_party_id(),
        rp_name=relying_party_name(),
        user_id=secrets.token_bytes(32),
        user_name=account_name,
        user_display_name=display_name,
        timeout=CEREMONY_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


def finish_registration(
    *, credential: dict[str, Any], expected_challenge: bytes
) -> RegisteredCredential:
    """Check a finished ceremony. Raises on anything that does not verify."""
    verified = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_rp_id=relying_party_id(),
        expected_origin=expected_origins(),
        require_user_verification=True,
    )
    response = credential.get("response")
    return RegisteredCredential(
        credential_id=bytes(verified.credential_id),
        public_key=bytes(verified.credential_public_key),
        sign_count=int(verified.sign_count),
        aaguid=verified.aaguid,
        user_verified=bool(verified.user_verified),
        backed_up=bool(verified.credential_backed_up),
        transports=_accepted_transports(
            response.get("transports") if isinstance(response, dict) else None
        ),
    )


def _accepted_transports(reported: Any) -> list[str]:
    """The transports the browser reported, keeping the ones WebAuthn defines.

    The value arrives from the client, and the column and the options sent back
    to a browser later hold whatever is kept, so anything the specification does
    not name is dropped.
    """
    if not isinstance(reported, list):
        return []
    kept: list[str] = []
    for value in reported:
        if not isinstance(value, str):
            continue
        try:
            AuthenticatorTransport(value)
        except ValueError:
            continue
        kept.append(value)
    return kept


async def store(
    session: AsyncSession,
    *,
    user_id: int,
    registered: RegisteredCredential,
    name: str,
) -> UserPasskey:
    """Keep a verified credential. The caller commits.

    Locking the account makes the limit authoritative even when two empty
    slots are inspected concurrently. There is no passkey row to lock when an
    account registers its first credential, so the stable parent is the
    serialization point.
    """
    users = await session.exec(select(User).where(User.id == user_id).with_for_update())
    if users.first() is None:
        raise ValueError("cannot store a passkey for an unknown user")
    if await count_for_user(session, user_id=user_id) >= MAX_PASSKEYS_PER_USER:
        raise PasskeyLimitReached

    row = UserPasskey(
        user_id=user_id,
        credential_id=registered.credential_id,
        public_key=registered.public_key,
        rp_id=relying_party_id(),
        sign_count=registered.sign_count,
        transports=registered.transports,
        aaguid=registered.aaguid,
        user_verified=registered.user_verified,
        backed_up=registered.backed_up,
        name=name[:MAX_NAME_LENGTH],
    )
    session.add(row)
    await session.flush()
    return row


def begin_authentication(*, credentials: Sequence[UserPasskey] = ()) -> Ceremony:
    """Options for answering with a credential.

    With no ``credentials`` the allow-list is empty, which is what lets
    somebody sign in without saying who they are first: the authenticator
    offers what it holds for this domain and the assertion names the
    credential. A step-up hands over the account's own rows, which it has
    already read, so the browser is asked for one of those.
    """
    allow = [PublicKeyCredentialDescriptor(id=row.credential_id) for row in credentials]
    options = webauthn.generate_authentication_options(
        rp_id=relying_party_id(),
        timeout=CEREMONY_TIMEOUT_MS,
        allow_credentials=allow or None,
        # Required, as at registration: the assertion proves the person as
        # well as the device, so the session it opens is a multi-factor one.
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Ceremony(
        options=_options_to_dict(options), challenge=bytes(options.challenge)
    )


async def find_by_credential_id(
    session: AsyncSession, *, credential_id: bytes, for_update: bool = False
) -> UserPasskey | None:
    statement = select(UserPasskey).where(UserPasskey.credential_id == credential_id)
    if for_update:
        statement = statement.with_for_update()
    rows = await session.exec(statement)
    return rows.first()


@dataclass(frozen=True)
class Assertion:
    """What answering with a credential proved."""

    passkey: UserPasskey
    user_verified: bool


@dataclass(frozen=True)
class AssertionRefusal:
    """Why an assertion proved nothing, and the credential it named.

    ``unknown`` is a credential id this deployment holds no row for,
    ``wrong_rp`` one registered while it answered to another domain, and
    ``invalid`` one whose signature did not check out. ``passkey`` is the row
    the id named where there is one, so the caller can write the refusal down
    against the account it belongs to. What the caller answers the client with
    is the same for all three.
    """

    reason: Literal["unknown", "wrong_rp", "invalid"]
    passkey: UserPasskey | None = None


async def finish_authentication(
    session: AsyncSession, *, credential: dict[str, Any], expected_challenge: bytes
) -> Assertion | AssertionRefusal:
    """Check an assertion and record that the credential was used.

    An :class:`AssertionRefusal` where nothing was proved, carrying which of
    the three it was and the credential the id named. An assertion that did not
    verify the person is one of the ones that does not verify: user
    verification is required here.
    """
    raw_id = credential.get("rawId") or credential.get("id")
    if not raw_id:
        return AssertionRefusal(reason="unknown")
    try:
        credential_id = webauthn.base64url_to_bytes(raw_id)
    except Exception:
        return AssertionRefusal(reason="unknown")

    row = await find_by_credential_id(
        session, credential_id=credential_id, for_update=True
    )
    if row is None:
        return AssertionRefusal(reason="unknown")

    rp_id = relying_party_id()
    if row.rp_id != rp_id:
        # Registered when this deployment answered to another name. It cannot
        # verify here, and saying so is better than a failed signature.
        return AssertionRefusal(reason="wrong_rp", passkey=row)

    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origins(),
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except Exception:
        return AssertionRefusal(reason="invalid", passkey=row)

    row.sign_count = int(verified.new_sign_count)
    row.last_used_at = utcnow()
    row.backed_up = bool(verified.credential_backed_up)
    session.add(row)
    await session.flush()
    return Assertion(passkey=row, user_verified=bool(verified.user_verified))


def challenge_in(credential: dict[str, Any]) -> str | None:
    """The challenge the browser signed, read back out of its own client data.

    The ceremony's response carries the challenge inside the bytes the
    authenticator signed over, so that is where it is read from. ``None`` where
    the response is not shaped like one.
    """
    response = credential.get("response")
    if not isinstance(response, dict):
        return None
    encoded = response.get("clientDataJSON")
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        client_data = json.loads(webauthn.base64url_to_bytes(encoded))
    except Exception:
        return None
    challenge = client_data.get("challenge") if isinstance(client_data, dict) else None
    if isinstance(challenge, str) and challenge:
        return challenge
    return None


@dataclass(frozen=True)
class PresentedPasskey:
    """A credential that verified against a challenge issued for it."""

    passkey_id: str
    user_id: int
    backed_up: bool


@dataclass(frozen=True)
class PresentationRefused:
    """A ceremony that proved nothing.

    ``reason`` is what to write down about the account where the refusal says
    something about it, and ``None`` where it does not. ``user_id`` is the
    account the presented credential belongs to, where the id named one.
    ``keep`` is how the caller ends the transaction: ``True`` to stand by what
    the attempt already wrote — the attempt counted against the challenge, the
    credential's signature counter — and ``False`` to put it back with the
    answer it bought.
    """

    reason: str | None
    keep: bool
    user_id: int | None = None

    async def settle(self, session: AsyncSession) -> None:
        """End the transaction the way :attr:`keep` says."""
        if self.keep:
            await session.commit()
        else:
            await session.rollback()


async def _claim(
    session: AsyncSession,
    *,
    credential: dict[str, Any],
    user_id: int | None,
    purposes: Sequence[ChallengePurpose],
    code_verifier: str,
) -> tuple[str, AuthChallenge] | PresentationRefused:
    """Find the challenge the browser signed and take one of its attempts.

    The challenge must have been issued to ``user_id`` — to no account at all
    where that is ``None`` — and, where it was begun with the app's S256
    challenge as its answer, be finished with the verifier behind it. Hands
    back the value, for the library to check the ceremony against, and the
    claimed row, for :func:`_spend`.
    """
    value = challenge_in(credential)
    if value is None:
        return PresentationRefused(reason=None, keep=False)

    challenge = await challenge_service.claim_attempt(
        session, value=value, purposes=purposes
    )
    if (
        challenge is None
        or challenge.user_id != user_id
        or (
            challenge.answer_hash is not None
            and not challenge_service.answered_by(
                challenge, value=value, answer=s256(code_verifier)
            )
        )
    ):
        # The attempt is counted whether or not the answer was any good, so
        # what it wrote stands.
        return PresentationRefused(reason=None, keep=True)
    return value, challenge


async def _spend(
    session: AsyncSession, challenge: AuthChallenge
) -> PresentationRefused | None:
    """Spend the claimed challenge, or the refusal when another request did."""
    if await challenge_service.consume(session, challenge):
        return None
    # Spent between the claim and here, so what it bought is not this request's
    # to take a second time.
    return PresentationRefused(reason=None, keep=False)


async def present_against_challenge(
    session: AsyncSession,
    *,
    user_id: int | None,
    credential: dict[str, Any],
    purposes: Sequence[ChallengePurpose],
    code_verifier: str = "",
) -> PresentedPasskey | PresentationRefused:
    """Take a credential's assertion against the challenge it signed, once.

    The challenge is found from what the browser signed, claimed, checked to
    belong to ``user_id``, the assertion verified, the credential checked to
    belong to the same account, and the challenge spent. ``user_id`` is the
    account a session or request already names — a step-up, a break-glass
    request — and ``None`` for a sign-in, whose challenge names nobody and
    whose assertion is what names the account.

    The caller commits or rolls back (see :class:`PresentationRefused`) and
    decides what the proof is worth; nothing here opens or upgrades anything.
    """
    claimed = await _claim(
        session,
        credential=credential,
        user_id=user_id,
        purposes=purposes,
        code_verifier=code_verifier,
    )
    if isinstance(claimed, PresentationRefused):
        return claimed
    value, challenge = claimed

    outcome = await finish_authentication(
        session,
        credential=credential,
        expected_challenge=webauthn.base64url_to_bytes(value),
    )
    if isinstance(outcome, AssertionRefusal):
        if outcome.reason == "wrong_rp" and outcome.passkey is not None:
            # Said in the log because it is an operator's answer, not the
            # account's: the deployment moved domain and the credentials made
            # under the old one cannot answer here.
            logger.warning(
                "passkey refused: the credential belongs to %s, "
                "this deployment answers to %s",
                outcome.passkey.rp_id,
                relying_party_id(),
            )
        return PresentationRefused(
            reason=outcome.reason,
            keep=True,
            user_id=outcome.passkey.user_id if outcome.passkey is not None else None,
        )
    if user_id is not None and outcome.passkey.user_id != user_id:
        # A credential that verified, belonging to somebody else. It is this
        # account's key that was asked for.
        return PresentationRefused(reason="other_account", keep=True)

    # Read off the row while it is attached: the caller may roll back, which
    # expires its attributes.
    presented = PresentedPasskey(
        passkey_id=str(outcome.passkey.id),
        user_id=outcome.passkey.user_id,
        backed_up=bool(outcome.passkey.backed_up),
    )
    return await _spend(session, challenge) or presented


async def register_against_challenge(
    session: AsyncSession,
    *,
    user_id: int | None,
    credential: dict[str, Any],
    purposes: Sequence[ChallengePurpose],
    code_verifier: str = "",
) -> RegisteredCredential | PresentationRefused:
    """Take a new credential against the challenge it was made for, once.

    The registration counterpart of :func:`present_against_challenge`, with
    the same claim and the same spend: ``user_id`` is the account adding a key,
    and ``None`` for a sign-up, whose challenge was issued before there was an
    account. The credential comes back verified and kept by nobody; the caller
    stores it, and a refusal is ended the same way as an assertion's.
    """
    claimed = await _claim(
        session,
        credential=credential,
        user_id=user_id,
        purposes=purposes,
        code_verifier=code_verifier,
    )
    if isinstance(claimed, PresentationRefused):
        return claimed
    value, challenge = claimed

    try:
        registered = finish_registration(
            credential=credential,
            expected_challenge=webauthn.base64url_to_bytes(value),
        )
    except Exception as exc:
        logger.warning(
            "passkey registration did not verify for user %s: %s: %s",
            user_id,
            type(exc).__name__,
            exc,
        )
        return PresentationRefused(reason=None, keep=True)
    return await _spend(session, challenge) or registered


async def rename(
    session: AsyncSession, *, user_id: int, passkey_id: Any, name: str
) -> UserPasskey | None:
    """Give the account's credential another name, and hand the row back.

    ``None`` when the account holds no such credential.
    """
    row = await session.get(UserPasskey, passkey_id)
    if row is None or row.user_id != user_id:
        return None
    row.name = name[:MAX_NAME_LENGTH]
    session.add(row)
    await session.flush()
    return row


async def remove(session: AsyncSession, *, user_id: int, passkey_id: Any) -> bool:
    row = await session.get(UserPasskey, passkey_id)
    if row is None or row.user_id != user_id:
        return False
    await session.delete(row)
    await session.flush()
    return True


def _options_to_dict(options: Any) -> dict[str, Any]:
    """The library's options as plain JSON-ready data.

    ``options_to_json`` renders every binary field the way the browser API
    expects it, so the shape the client receives is the library's rather than
    one assembled here.
    """
    import json

    return json.loads(webauthn.options_to_json(options))
