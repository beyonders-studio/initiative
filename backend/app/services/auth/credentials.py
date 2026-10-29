"""Reading the credential a request presents.

One reader for every transport. The HTTP dependency, the ``/uploads`` route and
the realtime sockets each decide which kinds of credential they accept and how
a refusal reaches the client; what a credential *is*, which account it names,
and what it records about the sign-in behind it are decided here, once. What
can be told without the database — the kind, a token's signature and expiry —
is read first by ``app.core.identify``; this is the half that looks it up.

What it records goes to ``app.core.auth_context``: the providers a session
satisfied and what they asserted, the markers its ``amr`` carries, which session
it was, and whether it was a personal API key and the guild
that key is limited to. Everything is cleared first, so a credential of another
kind never inherits what a previous one recorded.

Nothing here reads the account's status. Who may hold a session is the caller's
question, asked with the account in hand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.core.auth_context import SessionCredential, claims_from_provider_auth
from app.core.identify import CredentialKind, Identified
from app.core.security import UploadTokenClaims
from app.core.login_methods import SecondFactorRequirement
from app.core.messages import AuthMessages
from app.models.platform.api_key import UserApiKey
from app.models.platform.user import User
from app.schemas.platform.token import TokenPayload
from app.services.auth.assurance import policy_markers
from app.services.auth.subject import account_for_subject
from app.services.platform import api_keys as api_keys_service


@dataclass(frozen=True)
class Authenticated:
    """The account a credential names, and what the credential was."""

    user: User
    kind: CredentialKind
    #: The ``auth_sessions`` row a session token names, where it names one.
    session_id: uuid.UUID | None = None
    #: The key, for a personal API key; its scope is the caller's to apply.
    api_key: UserApiKey | None = None


class CredentialRefused(Exception):
    """The credential names nobody, or nobody who may use it here."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = status.HTTP_401_UNAUTHORIZED,
        scheme: str = "Bearer",
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.scheme = scheme

    def as_http(self) -> HTTPException:
        headers = (
            {"WWW-Authenticate": self.scheme}
            if self.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return HTTPException(
            status_code=self.status_code, detail=self.detail, headers=headers
        )


def asked_of_an_account(value: str | None) -> SecondFactorRequirement:
    """What the deployment asks of an account, from the rule
    ``second_factor_requirement`` as a query read it alongside something else
    (``rules.platform_rule_sql``).

    A value this version does not recognise reads as ``nobody``: asking for
    something this one cannot describe is worse than asking for nothing.
    """
    try:
        return SecondFactorRequirement(value)
    except ValueError:
        return SecondFactorRequirement.nobody


def _session_row_id(sid: str | None) -> uuid.UUID | None:
    if not sid:
        return None
    try:
        return uuid.UUID(sid)
    except ValueError:
        return None


_UNREADABLE = AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


async def _session(session: AsyncSession, token_data: TokenPayload) -> Authenticated:
    account = await account_for_subject(session, subject=token_data.sub)
    if account is None:
        raise CredentialRefused(
            AuthMessages.USER_NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND
        )
    user, asked = account
    # ``ver`` is what signing out everywhere moves.
    if token_data.ver is None or token_data.ver != user.token_version:
        raise CredentialRefused(AuthMessages.INVALID_TOKEN)
    session_id = _session_row_id(token_data.sid)
    auth_context.record(
        satisfied_providers=frozenset(token_data.sat or ()),
        satisfied_claims=claims_from_provider_auth(token_data.satd),
        # What the sign-in wrote about how it was made — the second-factor
        # marker where a code was presented, the passkey markers where a key
        # answered.
        session_amr=policy_markers(token_data.amr),
        asked_of_account=asked_of_an_account(asked),
        session_credential=(
            SessionCredential(session_id=session_id, token_version=token_data.ver)
            if session_id is not None
            else None
        ),
    )
    return Authenticated(user=user, kind=CredentialKind.session, session_id=session_id)


async def _upload_token(
    session: AsyncSession, upload: UploadTokenClaims
) -> Authenticated:
    user = (
        await session.exec(select(User).where(User.id == upload.user_id))
    ).one_or_none()
    if user is None:
        raise CredentialRefused(
            AuthMessages.USER_NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND
        )
    # The scoped token copied its minting session's satisfied set and markers,
    # so a policy-gated guild treats this request as that session.
    auth_context.record(
        satisfied_providers=upload.satisfied,
        satisfied_claims=upload.claims,
        session_amr=policy_markers(upload.markers),
    )
    return Authenticated(user=user, kind=CredentialKind.upload_token)


async def _api_key(session: AsyncSession, token: str) -> Authenticated | None:
    found = await api_keys_service.authenticate_api_key(session, token)
    if found is None:
        return None
    user, api_key = found
    auth_context.record(api_key_credential=True, api_key_guild_id=api_key.guild_id)
    return Authenticated(user=user, kind=CredentialKind.api_key, api_key=api_key)


async def authenticate(session: AsyncSession, identified: Identified) -> Authenticated:
    """The account a credential names, as one of the kinds it was read as.

    ``identified`` is what ``app.core.identify`` read locally; this is the
    half that asks the database. Raises :class:`CredentialRefused` for
    anything else. An installed plug-in's access token is never a person and is
    refused whatever the caller allows; a route that admits one reads it from
    :attr:`Identified.plugin_token`.
    """
    auth_context.reset()
    token, allow = identified.token, identified.allow
    if identified.refused is not None:
        raise CredentialRefused(identified.refused)
    if identified.access is not None:
        raise CredentialRefused(_UNREADABLE)
    if identified.upload is not None:
        return await _upload_token(session, identified.upload)
    if identified.session is not None:
        return await _session(session, identified.session)

    if token.startswith(api_keys_service.API_KEY_PREFIX):
        found = (
            await _api_key(session, token) if CredentialKind.api_key in allow else None
        )
        if found is None:
            raise CredentialRefused(_UNREADABLE)
        return found
    raise CredentialRefused(_UNREADABLE)
