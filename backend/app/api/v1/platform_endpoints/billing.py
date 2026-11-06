"""The external billing service's verbs, all ``POST /api/v1/billing/*``.

Machine-to-machine. Each request's envelope is verified over the raw body
before anything is parsed (``app.services.platform.billing.verify_billing_envelope``),
and its ``jti`` is spent on the system engine before any work
(``burn_jti``), so a replay does nothing at all. Not part of the OpenAPI
schema; no user is ever resolved.

Every verb takes a batch of up to 500 and answers each item on its own: an
item that doesn't validate, names no community, or fails is answered with an
error beside the others, which still land. The reference implementation of
the shapes is billing's simulator (``billing/devtools/initiative_v2.py`` in
initiative-billing).

* ``communities/sync``: each community's whole state at a version, taken only
  when newer than the one held. Under the ``initiative_billing`` role, scoped
  to each community in turn, one savepoint per item.
* ``statements``: signed entitlement statements, verified against billing's
  statement key, kept when newer, and handed to the installed plug-in.
* ``communities/read``: each community's status, usage, members, guests,
  name, the state version it holds and each statement's version.
* ``notices``: a notice for a community's seat, once per key.
* ``changes``: the change log after a cursor (``app.services.platform.billing_changes``).

Every verb names a community by the **reference** billing holds for it, never
by a row id of ours.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from sqlmodel import select

from app.api.deps import SessionDep, SystemSessionDep
from app.core.errors import CodedError
from app.core.messages import BillingMessages
from app.db import cohorts, post_commit
from app.db.request_context import Billing
from app.db.session import set_rls_context
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.plugin_entitlement import PluginEntitlement
from app.schemas.platform.billing import (
    ChangesRequest,
    CommunitiesReadRequest,
    CommunitySyncItem,
    CommunitySyncRequest,
    NoticeItem,
    NoticesRequest,
    StatementsRequest,
    read_entitlement_statement,
)
from app.services.marketplace import plugin_entitlements
from app.services.platform import billing as billing_service
from app.services.platform import billing_changes
from app.services.platform import guilds as guilds_service
from app.services.platform import identity_refs

router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)


async def _verified[M: BaseModel](request: Request, model: type[M]) -> M:
    """Envelope first, jti spent second, parse third (see module docstring)."""
    body = await request.body()
    claims = billing_service.verify_billing_envelope(
        method=request.method,
        path=request.url.path,
        headers=request.headers,
        body=body,
    )
    await billing_service.burn_jti(claims)
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=BillingMessages.INVALID_PAYLOAD,
        ) from exc


def _refs(items: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(item["community_ref"])
            for item in items
            if isinstance(item, dict) and isinstance(item.get("community_ref"), str)
        )
    )


@router.post("/communities/sync")
async def sync_communities(
    request: Request, session: SessionDep, system: SystemSessionDep
) -> dict:
    payload = await _verified(request, CommunitySyncRequest)
    guild_ids = await identity_refs.resolve_billing_refs(
        _refs(payload.communities), IdentityEntity.guild
    )
    results: list[dict[str, Any]] = []
    on_hold: list[int] = []
    for raw in payload.communities:
        ref = raw.get("community_ref") if isinstance(raw, dict) else None
        try:
            item = CommunitySyncItem.model_validate(raw)
        except ValidationError:
            results.append(
                {"community_ref": ref, "error": BillingMessages.INVALID_PAYLOAD}
            )
            continue
        guild_id = guild_ids.get(item.community_ref)
        if guild_id is None:
            results.append(
                {
                    "community_ref": item.community_ref,
                    "error": BillingMessages.COMMUNITY_NOT_FOUND,
                }
            )
            continue
        await set_rls_context(session, Billing(guild_id))
        try:
            async with session.begin_nested():
                synced = await billing_service.apply_community_sync(
                    session,
                    system,
                    guild_id=guild_id,
                    version=item.version,
                    fields=item.fields,
                )
        except CodedError as exc:
            results.append({"community_ref": item.community_ref, "error": exc.code})
            continue
        except Exception:
            logger.exception("billing: sync of guild %s failed", guild_id)
            results.append(
                {
                    "community_ref": item.community_ref,
                    "error": BillingMessages.ITEM_FAILED,
                }
            )
            continue
        if synced.went_on_hold:
            on_hold.append(guild_id)
        results.append({"community_ref": item.community_ref, "version": synced.version})
    await session.commit()
    for guild_id in on_hold:
        # Told once, on the way in, and on the system engine: the billing role
        # writes guild status and caps and nothing else.
        try:
            async with cohorts.system_session(guild_id) as system_session:
                await guilds_service.announce_on_hold(system_session, guild_id)
        except Exception:
            logger.exception(
                "billing: on-hold notice for guild %s not written", guild_id
            )
    return {"results": results}


@router.post("/statements")
async def statements(request: Request) -> dict:
    payload = await _verified(request, StatementsRequest)
    keys = billing_service.statement_keys()
    results: list[dict[str, Any]] = []
    for jws in payload.statements:
        try:
            if not isinstance(jws, str):
                raise ValueError("a statement is a compact JWS")
            claims = read_entitlement_statement(jws, keys)
        except ValueError:
            results.append(
                {"community_ref": None, "error": BillingMessages.INVALID_STATEMENT}
            )
            continue
        answer: dict[str, Any] = {
            "community_ref": claims.community_ref,
            "listing_uid": claims.listing_uid,
        }
        guild_id = await identity_refs.resolve_billing_ref(
            claims.community_ref, IdentityEntity.guild
        )
        if guild_id is None:
            results.append({**answer, "error": BillingMessages.COMMUNITY_NOT_FOUND})
            continue
        if await plugin_entitlements.listing_terms(claims.listing_uid) is None:
            results.append({**answer, "error": BillingMessages.LISTING_HAS_NO_TERMS})
            continue
        try:
            stored = await plugin_entitlements.store_statement(
                guild_id,
                claims.listing_uid,
                statement=jws,
                version=claims.version,
                values=claims.values,
            )
        except Exception:
            logger.exception("billing: statement for guild %s not stored", guild_id)
            results.append({**answer, "error": BillingMessages.ITEM_FAILED})
            continue
        if stored.applied:
            post_commit.spawn(
                plugin_entitlements.deliver_entitlement(guild_id, claims.listing_uid)
            )
        results.append({**answer, "version": stored.version})
    return {"results": results}


@router.post("/communities/read")
async def read_communities(request: Request, session: SessionDep) -> dict:
    payload = await _verified(request, CommunitiesReadRequest)
    refs = list(dict.fromkeys(payload.community_refs))
    guild_ids = await identity_refs.resolve_billing_refs(refs, IdentityEntity.guild)
    held = await _statement_versions(list(guild_ids.values()))
    out: list[dict[str, Any]] = []
    for ref in refs:
        guild_id = guild_ids.get(ref)
        if guild_id is None:
            continue
        await set_rls_context(session, Billing(guild_id))
        row = await billing_service.guild_billing_read(session, guild_id)
        if row is None:
            continue
        try:
            usage = await billing_service.guild_usage(guild_id)
        except CodedError:
            continue
        out.append(
            {
                "community_ref": ref,
                "status": row.status,
                "usage_bytes": usage.usage_bytes,
                "members": usage.member_count,
                "guests": usage.guest_count,
                "name": row.name,
                "version": row.billing_version,
                "statements": held.get(guild_id, {}),
            }
        )
    await session.commit()
    return {"communities": out}


async def _statement_versions(guild_ids: list[int]) -> dict[int, dict[str, int]]:
    """Each community's statement versions, by listing."""
    from app.db.session import SystemSessionLocal

    if not guild_ids:
        return {}
    async with SystemSessionLocal() as session:
        rows = (
            await session.exec(
                select(
                    PluginEntitlement.guild_id,
                    PluginEntitlement.listing_uid,
                    PluginEntitlement.version,
                ).where(PluginEntitlement.guild_id.in_(guild_ids))  # type: ignore[attr-defined]
            )
        ).all()
    out: dict[int, dict[str, int]] = {}
    for guild_id, uid, version in rows:
        out.setdefault(guild_id, {})[uid] = int(version)
    return out


@router.post("/notices")
async def notices(request: Request, session: SessionDep) -> dict:
    """Notices for communities' seats, from a fixed list, once per key.

    At least once, never lost, per notice:

    1. on the system engine — the billing role writes the event log and may
       not read it — a key already in the log is a replay, and tells nobody;
    2. on the system engine, the bell lines and the letters are written to the
       notice outbox, whose worker delivers and retries them, and committed;
    3. only then is the key claimed, on the billing session.

    A failure before step 3 leaves the key unclaimed, and billing's retry
    delivers it; a crash between 2 and 3 repeats the reminder rather than
    losing it. A community that is deleted or suspended is told nothing.
    """
    payload = await _verified(request, NoticesRequest)
    guild_ids = await identity_refs.resolve_billing_refs(
        _refs(payload.notices), IdentityEntity.guild
    )
    results: list[dict[str, Any]] = []
    for raw in payload.notices:
        key = raw.get("key") if isinstance(raw, dict) else None
        try:
            notice = NoticeItem.model_validate(raw)
        except ValidationError:
            results.append({"key": key, "error": BillingMessages.INVALID_PAYLOAD})
            continue
        guild_id = guild_ids.get(notice.community_ref)
        if guild_id is None:
            results.append(
                {"key": notice.key, "error": BillingMessages.COMMUNITY_NOT_FOUND}
            )
            continue
        try:
            delivered = await _deliver_notice(session, notice, guild_id)
        except Exception:
            logger.exception("billing: community notice %s not written", notice.key)
            await session.rollback()
            results.append(
                {"key": notice.key, "error": BillingMessages.NOTICE_NOT_DELIVERED}
            )
            continue
        results.append({"key": notice.key, "delivered": delivered})
    return {"results": results}


async def _deliver_notice(session, notice: NoticeItem, guild_id: int) -> bool:
    owner_user_id = (
        await identity_refs.resolve_billing_ref(
            notice.recipient_user_ref, IdentityEntity.user
        )
        if notice.recipient_user_ref
        else None
    )
    async with cohorts.system_session(guild_id) as system_session:
        if await billing_service.event_claimed(system_session, notice.key):
            return False
        delivered = await guilds_service.queue_billing_notice(
            system_session,
            guild_id,
            kind=notice.kind.value,
            day=notice.day,
            owner_user_id=owner_user_id,
        )
    # A concurrent delivery of the same notice may have claimed it meanwhile;
    # both wrote the notice, which is the at-least-once this accepts.
    await set_rls_context(session, Billing(guild_id))
    await billing_service.claim_community_notice(session, notice.key, guild_id=guild_id)
    await session.commit()
    return delivered


@router.post("/changes")
async def changes(request: Request) -> dict:
    payload = await _verified(request, ChangesRequest)
    try:
        page, cursor = await billing_changes.page(payload.after, payload.limit)
    except billing_changes.CursorInvalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=BillingMessages.INVALID_PAYLOAD,
        ) from None
    return {"changes": page, "cursor": cursor}
