"""Every Postgres advisory lock the app takes, and the one way it takes them.

An advisory lock is named by integers that share one space per database (and,
on the maintenance database, per cluster), so each purpose draws its name from
:class:`LockNamespace` and every lock goes through :func:`advisory_lock`.

A lock comes in one of two shapes, and Postgres keeps the two apart:

* **Keyed** — ``(namespace, key)``, the two-integer form. The key is an id, or,
  for anything composite, a 32-bit hash of text naming it. Two purposes never
  share a lock because they never share a namespace.
* **Singleton** — one lock for the whole purpose, taken with no key. The
  namespace's own value is the lock, in the single ``bigint`` form.

``@unique`` holds every value in the registry distinct, so neither shape can
repeat a name.
"""

from __future__ import annotations

import hashlib
from enum import IntEnum, unique

from sqlalchemy import BigInteger, ColumnElement, Integer, Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


def _tag(name: bytes) -> int:
    """A namespace spelled as up to four ASCII letters, so it reads back in
    ``pg_locks``."""
    return int.from_bytes(name, "big")


@unique
class LockNamespace(IntEnum):
    """One value per lock purpose.

    The singletons (taken with no key) come first; their values are the lock
    itself. Every other member is a namespace for the two-integer form.
    """

    # -- singletons ---------------------------------------------------------
    #: Applying the database prerequisites (``app.db.bootstrap``). Taken on the
    #: maintenance database as well, so it spans deployments on one cluster.
    DATABASE_BOOTSTRAP = 0x1417B007
    #: Migrating a database (``app.db.session.migration_lock``).
    MIGRATION = 0x1417A7E50D
    #: The test suite's migrations and role DDL, on the ``postgres`` database.
    TEST_SUITE_MIGRATION = 0x1417A7E5
    #: Copying local uploads into S3 (``app.db.backfill_uploads_to_s3``).
    UPLOAD_BACKFILL = 0x1014_5311
    #: Encrypting what was stored before STORAGE_ENCRYPTION was set
    #: (``app.services.storage_encryption``).
    STORAGE_ENCRYPTION = 0x53544F52454E43
    #: The first registrations taking turns, so one of them bootstraps.
    FIRST_ACCOUNT = 0x696E6974626F6F74
    #: Refreshing the marketplace registry's TUF metadata.
    MARKETPLACE_REFRESH = -0x307876F6777BC55F
    #: The demo deployment's pool pass, one process at a time.
    DEMO_POOL = 0x44454D4F504F4F4C

    # -- keyed by a guild ---------------------------------------------------
    #: Provisioning a guild's schema; key 0 orders the shared trigger functions.
    GUILD_PROVISION = _tag(b"PROV")
    #: Admitting a member under the guild's ``max_users``.
    MEMBER_CAP = _tag(b"USER")
    #: Admitting a guest under the guild's ``max_guests``.
    GUEST_CAP = _tag(b"GUES")
    #: Changes that could empty a guild's seat or impose a requirement on it.
    GUILD_SEATS = 8471
    #: Admitting an upload under the guild's ``max_storage_bytes``.
    STORAGE_QUOTA = _tag(b"STOR")
    #: Claiming a guild's next queued export.
    EXPORT_CLAIM = _tag(b"EXQ")
    #: Claiming a guild's next queued import.
    IMPORT_CLAIM = _tag(b"IMQ")
    #: Writing a guild's intake bindings.
    INTAKE_BINDINGS = _tag(b"INTB")
    #: One of a guild's query slots, keyed by guild and slot.
    QUERY_SLOT = _tag(b"QUER")
    #: One intake key in a guild, keyed by guild, stream and key.
    INTAKE_CASE = _tag(b"INTK")
    #: One moderation report target, keyed by guild, initiative and target.
    MODERATION_REPORT = _tag(b"MODR")
    #: One comment thread, keyed by guild, table and row: locking it and
    #: writing in it take turns.
    COMMENT_THREAD = _tag(b"CTHR")
    #: Placing or releasing a hold in a guild, and destroying the guild.
    CONTENT_HOLDS = _tag(b"HOLD")
    #: One poll, keyed by guild and poll.
    POST_POLL = _tag(b"POLL")
    #: One plug-in connection's token, keyed by guild, install and connection.
    PLUGIN_TOKEN = _tag(b"PTOK")
    #: The values one install keeps on one item, keyed by guild, install and
    #: item, written under the per-item caps.
    PLUGIN_METADATA = _tag(b"PMET")
    #: Changing one target's layouts, keyed by guild, tool and target.
    TOOL_LAYOUTS = _tag(b"LAYO")
    #: Putting tasks into one limited board column, keyed by guild and status.
    COLUMN_LIMIT = _tag(b"CLIM")
    #: Writing one property value, keyed by guild, item and property, so a
    #: change of a multi-select's options reads the value in its turn.
    PROPERTY_VALUE = _tag(b"PVAL")
    #: Creating one person's resumable uploads, keyed by guild and person, so
    #: two at once count each other.
    PENDING_UPLOADS = _tag(b"RESU")
    #: Which of one install's values are shown, keyed by guild and install:
    #: shared by each write while it reads the pinned definition, exclusive
    #: while the values are reconciled to a new one.
    PLUGIN_FIELDS = _tag(b"PFLD")
    #: Working out a guild's engagement levels, so one replica does each.
    ENGAGEMENT_LEVELS = _tag(b"ENGL")

    # -- keyed by an account ------------------------------------------------
    #: Creating communities under the daily limit.
    GUILD_CREATION = _tag(b"GCRE")
    #: Creating exports under the per-account cap.
    EXPORT_CAP = _tag(b"EXP")
    #: Creating imports under the per-account cap.
    IMPORT_CAP = _tag(b"IMP")
    #: Grant changes for one account in one guild, keyed by both.
    ACCESS_GRANT = _tag(b"PAMG")
    #: One account's DM mailbox.
    DM_QUEUE = _tag(b"DMQU")
    #: One account's device verification messages.
    DM_VERIFICATION = _tag(b"DMVF")
    #: One recipient's rolled-up notification line, keyed by the line. Every
    #: rollup takes it around finding the unread line and writing it.
    NOTIFICATION_LINE = _tag(b"NOTE")
    #: One person's reaction toggle on one target.
    REACTION_TOGGLE = _tag(b"REAC")
    #: Replacing one account's key for one tool resource.
    API_KEY_RESOURCE = _tag(b"KEYR")
    #: Provisioning an account for one address, keyed by the normalized address.
    ACCOUNT_ADDRESS = _tag(b"ADDR")
    #: Sign-ins from one app install, keyed by the account and the install.
    APP_INSTALL = _tag(b"INST")
    #: Claiming the lease to send to one plug-in about one community, keyed by
    #: both, for the short transaction that takes it (``community_hooks``).
    #: Never held across a send.
    PLUGIN_HOOK_SEND = _tag(b"PHSN")


def _text_key(text: str) -> int:
    """A stable signed 32-bit key for *text*, computed here so the text itself
    is never sent to the database."""
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big", signed=True)


def _lock_call(name: str, namespace: LockNamespace, key: int | str | None) -> Select:
    args: tuple[ColumnElement, ...]
    if key is None:
        args = (literal(int(namespace), BigInteger),)
    else:
        value = _text_key(key) if isinstance(key, str) else int(key)
        args = (literal(int(namespace), Integer), literal(value, Integer))
    return select(getattr(func, name)(*args))


async def advisory_lock(
    conn: AsyncSession | AsyncConnection,
    namespace: LockNamespace,
    key: int | str | None = None,
    *,
    wait: bool = True,
    xact: bool = True,
    shared: bool = False,
) -> bool:
    """Take the lock *namespace* names for *key* (a singleton when ``None``).

    Held to the end of the transaction by default; ``xact=False`` holds it for
    the connection until :func:`advisory_unlock` or the connection closes.
    ``wait=False`` returns at once, ``False`` when another holder has it.
    ``shared=True`` takes it beside other shared holders, and waits only for
    an exclusive one.
    """
    name = "pg_{}advisory_{}lock{}".format(
        "" if wait else "try_",
        "xact_" if xact else "",
        "_shared" if shared else "",
    )
    taken = await conn.scalar(_lock_call(name, namespace, key))
    return True if wait else bool(taken)


async def advisory_unlock(
    conn: AsyncConnection, namespace: LockNamespace, key: int | str | None = None
) -> None:
    """Release a lock :func:`advisory_lock` took with ``xact=False``."""
    await conn.scalar(_lock_call("pg_advisory_unlock", namespace, key))
