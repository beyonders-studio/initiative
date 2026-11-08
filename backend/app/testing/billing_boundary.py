"""Billing's side of the v2 envelope, for tests that post to its verbs.

A test configures this deployment with :func:`configure` (billing's boundary
key, the statement key, and nothing outbound) and posts with :func:`post`,
which signs the request as billing would. ``sign`` builds one envelope with
any claim overridden, for the refusal tests.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx2 import AsyncClient
from sqlalchemy import text

from app.core import config as config_module
from app.services.platform import billing_changes
from app.services.platform import billing_envelope as envelope
from app.testing.factories import STATEMENT_PUBLIC_PEM


def _pem_pair(key: ed25519.Ed25519PrivateKey) -> tuple[str, str]:
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return private, public


PRIVATE_PEM, PUBLIC_PEM = _pem_pair(ed25519.Ed25519PrivateKey.generate())
OTHER_PRIVATE_PEM, OTHER_PUBLIC_PEM = _pem_pair(ed25519.Ed25519PrivateKey.generate())


def configure(monkeypatch, *, managed: bool = False) -> None:
    """This deployment, configured to take billing's verbs. ``managed`` sets
    the portal URL too, so :func:`billing_managed` answers true."""
    settings = config_module.settings
    monkeypatch.setattr(settings, "BILLING_PUBLIC_KEY_PEM", PUBLIC_PEM)
    monkeypatch.setattr(
        settings, "BILLING_STATEMENT_PUBLIC_KEY_PEM", STATEMENT_PUBLIC_PEM
    )
    monkeypatch.setattr(settings, "BILLING_SERVICE_URL", None)
    monkeypatch.setattr(
        settings, "BILLING_URL", "https://billing.example.test" if managed else None
    )


def sign(
    path: str,
    body: bytes,
    *,
    private_pem: str = PRIVATE_PEM,
    typ: str = envelope.TYP,
    method: str = "POST",
    **claims: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": envelope.BILLING,
        "aud": envelope.TO_INITIATIVE,
        "iat": now,
        "exp": now + 60,
        "jti": uuid.uuid4().hex,
        "htm": method,
        "htp": path,
        "bsh": envelope.body_hash(body),
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, private_pem, algorithm="EdDSA", headers={"typ": typ})


async def post(
    client: AsyncClient,
    verb: str,
    payload: Any,
    *,
    token: str | None = None,
    **claims: Any,
):
    """Post ``payload`` to ``/api/v1/billing/{verb}``, signed as billing."""
    path = f"/api/v1/billing/{verb}"
    body = json.dumps(payload).encode()
    headers = {
        "Authorization": f"Bearer {token or sign(path, body, **claims)}",
        "Content-Type": "application/json",
    }
    return await client.post(path, content=body, headers=headers)


#: The change-log kinds of a community's lifecycle.
LIFECYCLE_KINDS = (
    "community.created",
    "community.deleted",
    "community.restored",
    "community.suspended",
    "community.unsuspended",
    "community.purged",
)


async def change_rows(session, guild_id: int, *, kinds=None) -> list[tuple[str, dict]]:
    """The change log's rows for ``guild_id``, oldest first, as (kind, data),
    whether or not they're visible to a page yet. ``session`` is the
    superuser fixture."""
    from sqlalchemy import text

    rows = (
        await session.exec(
            text(
                "SELECT kind, data FROM public.billing_changes WHERE guild_id = :g"
                " ORDER BY xid, id"
            ),
            params={"g": guild_id},
        )
    ).all()
    return [(r[0], dict(r[1] or {})) for r in rows if kinds is None or r[0] in kinds]


async def change_kinds(session, guild_id: int, *, kinds=LIFECYCLE_KINDS) -> list[str]:
    return [kind for kind, _data in await change_rows(session, guild_id, kinds=kinds)]


def configure_outbound(monkeypatch, url: str) -> None:
    """This deployment, configured to send billing its ping and reads at
    ``url``, signed with a handoff key of its own."""
    settings = config_module.settings
    monkeypatch.setattr(settings, "BILLING_SERVICE_URL", url)
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", OTHER_PRIVATE_PEM)
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_KEY_ID", "test-handoff-key")


def use_handoff_key(monkeypatch) -> str:
    """This deployment's handoff key, set; returns its public PEM, which is
    what billing verifies handoffs and Initiative's requests with."""
    settings = config_module.settings
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", OTHER_PRIVATE_PEM)
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_KEY_ID", "test-handoff-key")
    return OTHER_PUBLIC_PEM


async def served_changes(after: str | None = None) -> tuple[list[dict], str | None]:
    """Every change served after ``after``, once the cluster's transactions
    older than now have ended: the log is served only up to the oldest one
    still running, in any database, and the suite's other workers run theirs
    beside this one."""
    deadline = asyncio.get_running_loop().time() + 15
    async with _wait_connection() as conn:
        now = (
            await conn.execute(text("SELECT pg_current_xact_id()::text"))
        ).scalar_one()
        await conn.rollback()
        while True:
            passed = (
                await conn.execute(
                    text(
                        "SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint"
                        " > CAST(:now AS bigint)"
                    ),
                    {"now": int(now)},
                )
            ).scalar_one()
            await conn.rollback()
            if passed or asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.05)
    out: list[dict] = []
    cursor = after
    while True:
        page, cursor = await billing_changes.page(cursor, 2)
        out += page
        if not page:
            return out, cursor


def _wait_connection():
    from app.db import session as db_session

    return db_session.SystemSessionLocal.kw["bind"].connect()
