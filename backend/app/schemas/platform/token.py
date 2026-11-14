from app.schemas.base import SanitizedBaseModel


class Token(SanitizedBaseModel):
    access_token: str
    token_type: str = "bearer"
    #: Returned only to a caller that presented its refresh token in the body
    #: rather than as a cookie — a native client, which keeps it in the
    #: platform's secure storage and so needs the rotated one back. A browser
    #: gets it as a cookie it never reads, and this stays absent.
    refresh_token: str | None = None


class SessionAssurance(SanitizedBaseModel):
    """One provider's account of the authentication it performed, as carried
    in the access token's ``satd`` claim (see ``services.auth.assurance``)."""

    auth_time: int | None = None
    amr: list[str] = []
    acr: str | None = None
    #: What this provider asserted for the claims some community narrows it
    #: by. The community's rule about which values count is read live; this is
    #: only the fact of what was said.
    claims: dict[str, list[str]] = {}


class TokenPayload(SanitizedBaseModel):
    sub: str | None = None
    exp: int | None = None
    iat: int | None = None
    ver: int | None = None
    # The server-side session id, satisfied auth methods, and satisfied
    # provider ids — the guild auth-policy gate reads ``sat``.
    sid: str | None = None
    amr: list[str] | None = None
    sat: list[int] | None = None
    # Per-provider detail behind ``sat``, keyed by provider id as a string.
    # Absent when no provider contributed one (a password session).
    satd: dict[str, SessionAssurance] | None = None
