"""Reading the credential a realtime socket's first frame carries.

The socket's side of ``app.services.auth.credentials``, which every transport
reads a credential through: a session token, held to the same rules — ``ver`` included — that the HTTP path holds it to.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.core.identify import SOCKET_CREDENTIALS, CredentialKind, identify_token
from app.models.platform.user import User, UserStatus
from app.services.auth import credentials
from app.services.auth.credentials import CredentialRefused


async def authenticate_ws_token(token: str, session: AsyncSession) -> User | None:
    """The active account a socket's session token names.

    ``None`` (rather than raising) when it names nobody, so the caller can
    close the socket with a policy-violation code.

    What the credential proved is recorded in ``app.core.auth_context`` as it
    is for a request, so the ``establish_guild_access`` call that follows
    applies the guild auth-policy gate to the socket exactly as REST would, and
    the streams it joins keep which credential it was and ask again later
    whether it still stands (see ``app.services.content_sockets``). A session
    token with no ``sid`` names no sign-in to ask about and opens no socket.
    """
    try:
        authenticated = await credentials.authenticate(
            session, identify_token(token, SOCKET_CREDENTIALS)
        )
    except CredentialRefused:
        return None
    if (
        authenticated.kind is CredentialKind.session
        and authenticated.session_id is None
    ) or authenticated.user.status != UserStatus.active:
        auth_context.reset()
        return None
    return authenticated.user
