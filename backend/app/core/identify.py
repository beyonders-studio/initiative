"""What a request's credential is, as far as can be told without the database.

The half of ``app.services.auth.credentials`` that needs no database: tells the
kinds apart and checks what can be checked locally — a session or upload
token's signature, audience and expiry, an installed plug-in's seal. Personal API
keys are opaque here; only their lookup can say whom they name.

Read before any dependency runs, by the rate limiter and by the choice of
database pool, so both name the request the way authentication will. Naming
grants nothing: a credential admits a request only once
``credentials.authenticate`` has checked it against the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import jwt
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection

from app.core.messages import AuthMessages
from app.core.plugin_access_token import (
    AccessTokenError,
    InstallAccessToken,
    PluginAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.security import (
    SESSION_COOKIE_NAME,
    UploadTokenClaims,
    UploadTokenError,
    decode_session_token,
    verify_upload_token,
)
from app.schemas.platform.token import TokenPayload


class CredentialKind(str, Enum):
    """Which kind of credential authenticated a request."""

    #: An access token for a server-side session.
    session = "session"
    #: A personal API key.
    api_key = "api_key"
    #: A short-lived token that reaches ``/uploads`` and nothing else.
    upload_token = "upload_token"


#: What an ``Authorization: Bearer`` header or the session cookie may carry.
HEADER_CREDENTIALS = frozenset({CredentialKind.session, CredentialKind.api_key})
#: What may ride in a URL: only the narrow token minted to travel this way; a
#: session token never does, and an API key only in a feed's (below).
URL_CREDENTIALS = frozenset({CredentialKind.upload_token})
#: What a subscription feed's URL may carry: a personal API key, which the
#: route admits only when it names the one resource that route serves.
FEED_URL_CREDENTIALS = frozenset({CredentialKind.api_key})
#: What a realtime socket's first frame may carry.
SOCKET_CREDENTIALS = frozenset({CredentialKind.session})


@dataclass(frozen=True)
class Identified:
    """A credential, read locally.

    At most one of ``session``, ``upload`` and ``access`` is set, or
    ``refused``; with none of them the credential is opaque — an API key, for
    the database to name.
    """

    token: str
    allow: frozenset[CredentialKind]
    #: Whether it arrived in an ``Authorization: Bearer`` header, the only
    #: place an installed plug-in's token is read from.
    bearer: bool = False
    session: TokenPayload | None = None
    upload: UploadTokenClaims | None = None
    access: InstallAccessToken | PluginAccessToken | None = None
    #: Why it was refused, when its local check failed.
    refused: str | None = None

    @property
    def plugin_token(self) -> InstallAccessToken | PluginAccessToken | None:
        """The installed plug-in's or plug-in's token, when it came as a bearer."""
        return self.access if self.bearer else None

    @property
    def limit_key(self) -> str | None:
        """Whom the rate limiter counts this request against, or ``None`` when
        nobody can be named without the database."""
        if self.session is not None:
            return f"subject:{self.session.sub}"
        if self.upload is not None:
            return f"user:{self.upload.user_id}"
        token = self.plugin_token
        if isinstance(token, InstallAccessToken):
            return f"install:{token.client_id}:{token.guild_id}:{token.install_id}"
        if isinstance(token, PluginAccessToken):
            return f"plugin:{token.client_id}"
        return None


def _is_a_jwt(token: str) -> bool:
    """Whether ``token`` is a JWT, whatever it says and whoever signed it."""
    try:
        jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return False
    return True


def identify_token(
    token: str, allow: frozenset[CredentialKind], *, bearer: bool = False
) -> Identified:
    """Read ``token`` as one of the kinds in ``allow``, locally.

    The kinds tell themselves apart without being told: an installed plug-in's
    token by its prefix, the two token kinds by being JWTs with their own
    audiences, and an API key by being neither.
    """
    if is_access_token(token):
        try:
            access = unseal_access_token(token)
        except AccessTokenError:
            return Identified(
                token,
                allow,
                bearer=bearer,
                refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            )
        return Identified(token, allow, bearer=bearer, access=access)
    if not _is_a_jwt(token):
        return Identified(token, allow, bearer=bearer)
    if CredentialKind.upload_token in allow:
        try:
            upload = verify_upload_token(token)
        except UploadTokenError:
            pass
        else:
            return Identified(token, allow, bearer=bearer, upload=upload)
    if CredentialKind.session in allow:
        try:
            payload = TokenPayload(**decode_session_token(token))
        except jwt.PyJWTError:
            return Identified(
                token,
                allow,
                bearer=bearer,
                refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            )
        if not payload.sub:
            return Identified(
                token, allow, bearer=bearer, refused=AuthMessages.INVALID_TOKEN_PAYLOAD
            )
        return Identified(token, allow, bearer=bearer, session=payload)
    return Identified(
        token, allow, bearer=bearer, refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    )


class Presented(NamedTuple):
    """The credential a request presents, and where it arrived."""

    token: str
    #: Whether it came in an ``Authorization: Bearer`` header rather than the
    #: session cookie.
    bearer: bool


def bearer_token(headers: Headers) -> str | None:
    """The token an ``Authorization`` header carries under the ``Bearer``
    scheme (any case), or ``None`` when there is none."""
    scheme, _, param = headers.get("authorization", "").partition(" ")
    return param if scheme.lower() == "bearer" and param else None


def presented_credential(connection: HTTPConnection) -> Presented | None:
    """The credential a request presents: its bearer header when it carries
    one, and otherwise its session cookie. ``None`` when it presents neither.

    Every reader of a request's credential asks this, so they all agree on
    which one the request carries.
    """
    token = bearer_token(connection.headers)
    if token:
        return Presented(token, bearer=True)
    cookie = connection.cookies.get(SESSION_COOKIE_NAME)
    return Presented(cookie, bearer=False) if cookie else None


def identify(connection: HTTPConnection) -> Identified | None:
    """The credential a request's bearer header or session cookie carries,
    read once: a session or a personal API key. ``None`` when there is none.
    """
    if hasattr(connection.state, "identified"):
        return connection.state.identified
    presented = presented_credential(connection)
    identified = (
        identify_token(presented.token, HEADER_CREDENTIALS, bearer=presented.bearer)
        if presented is not None
        else None
    )
    connection.state.identified = identified
    return identified


def bearer_plugin_token(
    connection: HTTPConnection,
) -> InstallAccessToken | PluginAccessToken | None:
    """The installed plug-in's or plug-in's token in the request's bearer header,
    unsealed. ``None`` when there is none or it does not unseal."""
    identified = identify(connection)
    return identified.plugin_token if identified is not None else None


def identify_url_token(
    connection: HTTPConnection, allow: frozenset[CredentialKind] = URL_CREDENTIALS
) -> Identified | None:
    """The credential a request's ``?token=`` carries, as one of ``allow``,
    read once for each. ``None`` when there is none.

    ``allow`` is what a URL may carry unless a route says otherwise: a
    subscription feed passes :data:`FEED_URL_CREDENTIALS`."""
    read: dict[frozenset[CredentialKind], Identified | None] = getattr(
        connection.state, "identified_url", {}
    )
    if allow not in read:
        token = connection.query_params.get("token")
        read[allow] = identify_token(token, allow) if token else None
        connection.state.identified_url = read
    return read[allow]
