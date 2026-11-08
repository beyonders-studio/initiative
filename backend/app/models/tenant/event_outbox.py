"""Append-only change log, written by the capture trigger.

One row per changed content row, stamped by the generic capture trigger the
provisioning pipeline installs on every evented guild-content table. The row
carries **identifiers and changed column names only** — never a value. A
consumer learns *that* something changed and reads the current state back
through the REST API, where the six gates apply to the read.

Alongside the resource it names, a row carries the addressable resources
between that resource and its initiative (``parents``), because a change is
rarely interesting only where it happened: a comment moves a thread and the
count on the card its parent shows.

``initiative_id`` is resolved by the trigger from the same ``INITIATIVE_PATHS``
declaration that renders the table's RLS policies, so an event is scoped exactly
like the row it describes. The outbox's own read policy asks the initiative and
the sharing of the tool the change names (``dac_tool``/``dac_id``), as a search
entry's does.

Delivery state is not held here: this is a log, and each subscription tracks its
own position in it (``webhook_subscriptions.cursor_event_id``). One row can
therefore serve any number of subscribers, and retention is a plain age sweep.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

#: The three actions the trigger emits. A soft delete is reported as ``deleted``
#: and a restore as ``created``, so a consumer never has to know our
#: ``deleted_at`` convention to notice that a row came or went.
ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"
ACTIONS = (ACTION_CREATED, ACTION_UPDATED, ACTION_DELETED)


class EventOutbox(SQLModel, table=True):
    __tablename__ = "event_outbox"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )

    # ``txid_current()`` of the writing transaction. Every row a single
    # transaction produced shares one value, which is what lets the poller
    # deliver a transaction as one batched envelope instead of N envelopes.
    txn_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    # The actor and initiative columns are WEAK references — plain ints, no FK.
    #
    # The trigger fires while a row is being deleted, including when that
    # deletion is the cascade from removing the initiative or user the event
    # names. A foreign key would make the log's own insert fail that delete, so
    # purging an initiative would error instead of purging. Weak refs let the
    # log outlive what it describes; retention sweeps the orphans, and RLS still
    # resolves initiative_id through initiative_access (an initiative that no
    # longer exists resolves to guild-admin-only).
    #
    # actor_user_id is NULL for a system-attributed write (background jobs).
    actor_user_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # The installed plug-in whose request wrote the change, read from the same
    # request context as actor_user_id and weak for the same reason: removing
    # a plug-in leaves its history in place. Set independently of actor_user_id,
    # so a plug-in acting as its community names no person, and one acting for a
    # member names both.
    actor_install_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # NULL for a guild-wide event (a tag, say) — a row that belongs to no
    # initiative. The access function reads that as "the initiative gate has
    # nothing to decide" and admits any guild member, which is the right
    # disclosure for a row every member can already read. The trigger only
    # writes NULL where a registry says to; an initiative-scoped row whose
    # lookup fails is skipped instead.
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True),
    )

    # The table the change happened to, and its primary key.
    resource_type: str = Field(sa_column=Column(String(length=63), nullable=False))
    resource_id: int = Field(sa_column=Column(Integer, nullable=False))

    action: str = Field(sa_column=Column(String(length=16), nullable=False))

    # Changed column NAMES. Empty on create and delete, where the whole row
    # came or went and naming every column would say nothing.
    changed: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String(length=63)), nullable=False, server_default="{}"),
    )

    # The addressable resources between this one and its initiative, innermost
    # first: ``[{"type": "tasks", "id": 4}, {"type": "projects", "id": 7}]`` for
    # a comment on a task. Identifiers like the rest of the row — a consumer
    # that wants a parent reads it back through the route that serves it.
    #
    # Empty for a resource that hangs off nothing but its initiative, which is
    # every tool's own table. The chain comes from the same INITIATIVE_PATHS
    # walk that stamps ``initiative_id``, stopping at each resource that has a
    # route of its own.
    parents: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )

    # The tool instance whose sharing governs the change: the resource itself
    # when it is a tool, else the outermost tool in ``parents``. Stamped by the
    # capture trigger, like the pair a search entry carries, so the read policy
    # asks a person's sharing without walking the chain. NULL for a change that
    # sits under no tool (a tag), which answers to the initiative gate alone.
    dac_tool: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    dac_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
