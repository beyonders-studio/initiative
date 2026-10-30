"""Payloads for the billing service's verbs (``POST /api/v1/billing/*``).

Every verb takes a batch of up to :data:`BATCH_MAX` items and answers each on
its own, so one bad item never refuses the rest. The outer body is parsed
first; each item is validated by itself, and one that doesn't validate is
answered with an error beside the others. Parsed from the verified request
body (see ``app.services.platform.billing_envelope``) rather than by FastAPI's
body machinery, and excluded from the OpenAPI schema.

The reference implementation of these shapes is billing's simulator,
``billing/devtools/initiative_v2.py`` in initiative-billing.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import date
from enum import Enum
from typing import Annotated, Any, Optional

import jwt
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.messages import BillingMessages
from app.core.rules import COMMUNITY_RULES, SYNCED_RULES, Slot
from app.core.security import PUBLIC_KEY_JWT_ALGORITHM
from app.models.platform.identity_ref import REF_MAX_LENGTH
from app.models.platform.marketplace import UID_LENGTH
from app.models.platform.guild import BILLING_SETTABLE_STATUSES, CommunityStatus
from app.schemas.base import SanitizedBaseModel

#: The most items one call carries.
BATCH_MAX = 500
#: The highest version billing may send: a JSON number every client reads
#: exactly.
MAX_VERSION = 2**53 - 1

CommunityRef = Annotated[
    str, StringConstraints(min_length=1, max_length=REF_MAX_LENGTH)
]


class BillingBatch(SanitizedBaseModel):
    """A batch's outer shape: a list and its size. Each item is validated in
    its own turn, so one malformed item is answered as such and its
    neighbours still apply."""

    model_config = ConfigDict(extra="forbid")


class CommunitySyncRequest(BillingBatch):
    """Body of ``communities/sync``."""

    communities: list[Any] = Field(min_length=1, max_length=BATCH_MAX)


class SyncedRule(SanitizedBaseModel):
    """One of the deployment's rules for a community, beside its plan. A key
    this build does not know is ignored, as a capability name is."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    value: StrictBool | StrictInt

    @model_validator(mode="after")
    def _fits_its_rule(self) -> SyncedRule:
        rule = COMMUNITY_RULES.get(self.key)
        if rule is None:
            return self
        on_off = rule.slot is Slot.enabled
        if (
            self.key not in SYNCED_RULES
            or on_off != isinstance(self.value, bool)
            or not 0 <= self.value <= MAX_VERSION
        ):
            raise ValueError(BillingMessages.RULE_NOT_SYNCED)
        return self


class CommunityFields(SanitizedBaseModel):
    """What billing holds a community to, whole, at one version. Every field
    is sent every time: billing sends its desired state, never a patch, so a
    capability or a cap that drops off a plan is withdrawn by the same write.

    ``None`` is unlimited for a cap and no paid plan for ``tier_name``."""

    model_config = ConfigDict(extra="forbid")

    tier_name: Optional[str] = Field(max_length=64)
    max_storage_bytes: Optional[int] = Field(ge=0)
    max_users: Optional[int] = Field(ge=1)
    max_guests: Optional[int] = Field(ge=0)
    feature_keys: list[str] = Field(max_length=64)
    status: CommunityStatus
    #: The deployment's other rules for the community, whole: a rule left out
    #: falls back to the community's own. A sender that predates the field
    #: sets none.
    rules: list[SyncedRule] = Field(default_factory=list, max_length=64)

    @field_validator("rules")
    @classmethod
    def _once_each(cls, value: list[SyncedRule]) -> list[SyncedRule]:
        if len({rule.key for rule in value}) != len(value):
            raise ValueError(BillingMessages.RULE_NOT_SYNCED)
        return value

    @field_validator("status")
    @classmethod
    def _billing_sets_it(cls, value: CommunityStatus) -> CommunityStatus:
        # Suspension is the platform operator's, and deletion is deletion's.
        if value not in BILLING_SETTABLE_STATUSES:
            raise ValueError(BillingMessages.STATUS_NOT_SETTABLE)
        return value


class CommunitySyncItem(SanitizedBaseModel):
    """One community's state at ``version``. Taken only when ``version`` is
    newer than the one held; answered with the version held either way."""

    model_config = ConfigDict(extra="forbid")

    community_ref: CommunityRef
    version: int = Field(ge=1, le=MAX_VERSION, strict=True)
    fields: CommunityFields


class StatementsRequest(BillingBatch):
    """Body of ``statements``: signed entitlement statements, each the
    current one for its (community, listing)."""

    statements: list[Any] = Field(min_length=1, max_length=BATCH_MAX)


class CommunitiesReadRequest(BillingBatch):
    """Body of ``communities/read``."""

    community_refs: list[CommunityRef] = Field(min_length=1, max_length=BATCH_MAX)


class NoticesRequest(BillingBatch):
    """Body of ``notices``."""

    notices: list[Any] = Field(min_length=1, max_length=BATCH_MAX)


class BillingCommunityNoticeKind(str, Enum):
    """What a community notice says. A closed set: billing picks one, and the
    words are ours."""

    trial_ending = "trial_ending"
    trial_ended = "trial_ended"
    #: The plan is paused, and the community goes on hold on ``day`` unless it
    #: is resumed. Sent from the pause on, and again as the day nears.
    pause_reminder = "pause_reminder"


class NoticeItem(SanitizedBaseModel):
    """One notice for a community's seat. No free text crosses.

    ``key`` is billing's idempotency key for the notice, so a retried delivery
    tells nobody twice. ``recipient_user_ref`` is the billing reference of the
    person billing holds as the community's owner, or None; either way the
    community's current superadmins hear it when that person is not a member
    any more. A field this deployment doesn't know is ignored: the words are
    ours, so nothing billing adds can reach anybody."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=128)
    community_ref: CommunityRef
    kind: BillingCommunityNoticeKind
    #: The day the notice is about: the trial's end, or the day a paused
    #: community goes on hold.
    day: date
    recipient_user_ref: Optional[str] = Field(default=None, max_length=REF_MAX_LENGTH)


class ChangesRequest(BillingBatch):
    """Body of ``changes``: the log after ``after`` (an opaque cursor this
    deployment handed out, or None for the start)."""

    after: Optional[str] = Field(default=None, max_length=64)
    limit: int = Field(default=BATCH_MAX, ge=1, le=BATCH_MAX)


class BillingPortalHandoffResponse(SanitizedBaseModel):
    """Billing-portal handoff token and its lifetime in seconds."""

    handoff_token: str
    expires_in_seconds: int


#: The most a statement's values may weigh, serialized.
MAX_ENTITLEMENT_VALUES_BYTES = 16 * 1024
#: The highest version a statement may carry: a JSON number every client reads
#: exactly.
MAX_ENTITLEMENT_VERSION = 2**53 - 1
#: The most a whole signed statement may weigh: its values at their bound,
#: base64url-encoded, with room for the header, the other claims and the
#: signature.
MAX_ENTITLEMENT_STATEMENT_BYTES = 32 * 1024
#: The only header a statement is taken under.
ENTITLEMENT_STATEMENT_ALG = "EdDSA"
ENTITLEMENT_STATEMENT_TYPE = "initiative-entitlement+jwt"
#: Who issues statements.
ENTITLEMENT_STATEMENT_ISSUER = "initiative-billing"
#: An Ed25519 signature's length in bytes.
_ED25519_SIGNATURE_BYTES = 64


class EntitlementStatementClaims(SanitizedBaseModel):
    """What a signed entitlement statement says: the current statement for one
    (community, listing). ``values`` is a flat object whose keys belong to the
    plug-in, and ``version`` rises with every change.

    Claims this deployment does not read (``iat``, ``kid`` in the header) are
    left to the plug-in, which verifies the whole statement again.
    """

    model_config = ConfigDict(extra="ignore")

    iss: str = Field(strict=True)
    community_ref: str = Field(min_length=1, max_length=REF_MAX_LENGTH, strict=True)
    listing_uid: str = Field(min_length=UID_LENGTH, max_length=UID_LENGTH, strict=True)
    version: int = Field(ge=1, le=MAX_ENTITLEMENT_VERSION, strict=True)
    values: dict[str, Any] = Field(strict=True)

    @field_validator("iss")
    @classmethod
    def _issued_by_billing(cls, value: str) -> str:
        if value != ENTITLEMENT_STATEMENT_ISSUER:
            raise ValueError("iss is not the issuer")
        return value

    @field_validator("values")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"))) > MAX_ENTITLEMENT_VALUES_BYTES:
            raise ValueError("values is too large")
        return value


def _b64url(segment: str) -> bytes:
    """One compact-JWS segment, decoded: unpadded base64url and nothing else."""
    if not segment or "=" in segment:
        raise ValueError("not a base64url segment")
    return base64.b64decode(
        segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True
    )


def _json_object(segment: str) -> dict[str, Any]:
    def _refuse_constant(name: str) -> None:
        raise ValueError(f"{name} is not JSON")

    decoded = json.loads(_b64url(segment), parse_constant=_refuse_constant)
    if not isinstance(decoded, dict):
        raise ValueError("not a JSON object")
    return decoded


def read_entitlement_statement(
    statement: str, keys: tuple[Any, ...]
) -> EntitlementStatementClaims:
    """The claims of a compact-JWS entitlement statement signed by one of
    ``keys`` (the statement key, never the boundary key).

    Raises ``ValueError`` unless the statement is at most
    :data:`MAX_ENTITLEMENT_STATEMENT_BYTES`, the header is exactly
    :data:`ENTITLEMENT_STATEMENT_ALG` with :data:`ENTITLEMENT_STATEMENT_TYPE`,
    the signature segment is the length of an Ed25519 signature and verifies
    under one of ``keys``, and the claims hold everything
    :class:`EntitlementStatementClaims` names.
    """
    try:
        if (
            not isinstance(statement, str)
            or len(statement) > MAX_ENTITLEMENT_STATEMENT_BYTES
        ):
            raise ValueError("not a statement")
        parts = statement.split(".")
        if len(parts) != 3:
            raise ValueError("not a compact JWS")
        header_segment, claims_segment, signature_segment = parts
        header = _json_object(header_segment)
        if (
            header.get("alg") != ENTITLEMENT_STATEMENT_ALG
            or header.get("typ") != ENTITLEMENT_STATEMENT_TYPE
        ):
            raise ValueError("not an entitlement statement header")
        if len(_b64url(signature_segment)) != _ED25519_SIGNATURE_BYTES:
            raise ValueError("not an Ed25519 signature")
        if not any(_signed_by(statement, key) for key in keys):
            raise ValueError("not signed by the statement key")
        return EntitlementStatementClaims.model_validate(_json_object(claims_segment))
    except (ValueError, binascii.Error, UnicodeDecodeError, ValidationError) as exc:
        raise ValueError(BillingMessages.INVALID_STATEMENT) from exc


def _signed_by(statement: str, key: Any) -> bool:
    try:
        jwt.decode(
            statement,
            key,
            algorithms=[PUBLIC_KEY_JWT_ALGORITHM],
            issuer=ENTITLEMENT_STATEMENT_ISSUER,
            options={"verify_aud": False, "require": ["iss"]},
        )
    except jwt.PyJWTError:
        return False
    return True
