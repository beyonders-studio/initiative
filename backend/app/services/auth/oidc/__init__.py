"""OpenID Connect relying-party building blocks.

Small, independently-testable units — discovery, the id_token verifier, the
JWKS key resolver, the PKCE/nonce flow state, and the ``OidcProvider`` that
composes them into the begin/complete relying-party flow. Identity resolution
against the database is the caller's step after ``complete``.
"""

from app.services.auth.oidc.discovery import (
    DiscoveryError,
    OidcDiscovery,
    OidcMetadata,
)
from app.services.auth.oidc.flow_state import (
    FlowStateError,
    OidcFlowState,
    create_flow_state,
    decode_flow_state,
)
from app.services.auth.oidc.id_token import (
    IdTokenVerificationError,
    verify_id_token,
)
from app.services.auth.oidc.jwks import JwksResolutionError, JwksResolver
from app.services.auth.oidc.provider import (
    OidcBegin,
    OidcClientConfig,
    OidcCompletion,
    OidcFlowError,
    OidcProvider,
)

__all__ = [
    "DiscoveryError",
    "FlowStateError",
    "IdTokenVerificationError",
    "JwksResolutionError",
    "JwksResolver",
    "OidcBegin",
    "OidcClientConfig",
    "OidcCompletion",
    "OidcDiscovery",
    "OidcFlowError",
    "OidcFlowState",
    "OidcMetadata",
    "OidcProvider",
    "create_flow_state",
    "decode_flow_state",
    "verify_id_token",
]
