"""Pitches, and the links that hand them out.

A pitch is an ordinary community, made from an uploaded bundle and tailored in
the app by the pitch editors, who are its admins. Publishing it is exporting
it: a copy imports the pitch's newest finished community export, so edits
nobody has published never reach a visitor.

Pitches and the pool's communities are created by the demo host, an account
nobody signs in as, which holds their seat.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import exists, func, tuple_, update
from sqlmodel import select
from sqlmodel.sql.expression import SelectOfScalar
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import usernames
from app.core.config import settings
from app.core.image_headers import validate_image
from app.db import cohorts
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.demo import accounts
from app.models.platform.demo import DemoAccount, DemoLink, DemoSandbox, LinkState
from app.models.platform.guild import CommunityRole, CommunityStatus, Guild
from app.models.platform.guild_image import IMAGE_SPECS, GuildImageVariant
from app.models.platform.user import User
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.schemas.platform.demo import DemoDirectoryCard
from app.schemas.tenant.import_job import BackupPlanPerson
from app.services.import_engine import backup as backup_service
from app.services.import_engine import worker as import_worker
from app.services.import_engine.common import handle_key
from app.services.platform import app_settings as app_settings_service
from app.services.platform import guild_images, guild_purge
from app.services.platform import guilds as guilds_service

#: How long a link lasts unless it is made for longer, or for good.
LINK_LIFETIME = timedelta(days=30)
#: What a visitor may be in their copy.
LINK_ROLES = (CommunityRole.member, CommunityRole.admin, CommunityRole.superadmin)
#: How long making a pitch waits for its import, and how often it looks.
IMPORT_TIMEOUT_SECONDS = 30 * 60
IMPORT_POLL_SECONDS = 1.0


def hash_token(token: str) -> bytes:
    """How a link's token is kept and looked up."""
    return hashlib.sha256(token.encode()).digest()


def link_url(token: str) -> str:
    """The address a link's token is handed out at. The token rides in the
    fragment, which the browser keeps to itself."""
    return f"{settings.APP_URL.rstrip('/')}/demo#{token}"


def link_state(link: DemoLink, now: datetime) -> LinkState:
    """Whether the link still opens copies, and if not, why."""
    if link.revoked_at is not None:
        return LinkState.revoked
    if link.expires_at is not None and link.expires_at <= now:
        return LinkState.expired
    if (
        link.max_redemptions is not None
        and link.redemption_count >= link.max_redemptions
    ):
        return LinkState.used_up
    return LinkState.live


async def seat_cast(
    session: AsyncSession,
    *,
    guild_id: int,
    people: list[BackupPlanPerson],
    actor_id: int,
) -> dict[str, int]:
    """Seat as members of the community the personas among ``people``, the
    people a bundle names, under the names it gives them. Returns their ids by
    handle, as an import maps people.

    A persona is an account nobody signs in to that is not a visitor's and not
    the demo host."""
    named: dict[tuple[str, int], BackupPlanPerson] = {}
    for person in people:
        name, digits = usernames.parse_handle(person.handle)
        if digits is not None and len(digits) == usernames.DISCRIMINATOR_DIGITS:
            named[(name.lower(), int(digits))] = person
    if not named:
        return {}
    personas = await session.exec(
        select(User).where(
            tuple_(func.lower(User.username), User.discriminator).in_(list(named)),
            accounts.unloginable(),
            User.id != actor_id,
            ~exists().where(DemoAccount.user_id == User.id),
        )
    )
    seated: dict[str, int] = {}
    for user in personas.all():
        person = named[(user.username.lower(), user.discriminator)]
        await guilds_service.ensure_membership(
            session, guild_id=guild_id, user_id=user.id, actor_user_id=actor_id
        )
        if person.name:
            await guilds_service.set_member_display_name(
                session, guild_id=guild_id, user_id=user.id, display_name=person.name
            )
        seated[handle_key(person.handle)] = cast(int, user.id)
    return seated


async def make_pitch(
    *,
    bundle: Path,
    name: str,
    logo: bytes | None = None,
    editors: Sequence[str] = (),
    directory: DemoDirectoryCard | None = None,
) -> int:
    """Make a pitch named ``name`` from ``bundle``, with ``logo`` as its icon,
    and publish it. Returns its id.

    The accounts ``editors`` names by handle are made its admins, the
    personas the bundle names are seated in it, and its dates move from the
    bundle's export to now. With ``directory`` it is listed in the community
    directory with that card, and its initiatives take the card's join
    policy. The import runs here; the export is queued once it is done."""
    icon = validate_image(IMAGE_SPECS[GuildImageVariant.icon], logo) if logo else None
    # Refused here, before a community is made for it.
    plan = await asyncio.to_thread(
        backup_service.plan_backup, bundle, existing_initiative_names=set()
    )
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        editor_ids = []
        for handle in editors:
            editor = await accounts.by_handle(session, handle)
            if editor is None:
                raise ValueError(f"no account is {handle}")
            editor_ids.append(editor.id)
        host = await accounts.demo_host(session)
        guild = await guilds_service.provision_new_guild(
            session, name=name, creator=host
        )
        guild_id = cast(int, guild.id)
        await guilds_service.welcome_new_guild(guild_id, owner_user_id=host.id)
        if icon is not None:
            await guild_images.set_images(
                session, guild_id=guild_id, renditions={GuildImageVariant.icon: icon}
            )
        for editor_id in editor_ids:
            await guilds_service.ensure_membership(
                session,
                guild_id=guild_id,
                user_id=editor_id,
                role=CommunityRole.admin,
                force_role=True,
                actor_user_id=host.id,
            )
        seated = await seat_cast(
            session, guild_id=guild_id, people=plan.people, actor_id=host.id
        )
        if directory is not None:
            await _list(session, guild, directory)
        await session.commit()
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        job = await backup_service.stage_backup_job(
            session,
            guild_id=guild_id,
            user=host,
            payload=bundle,
            status=ImportJobStatus.queued,
            anchor=datetime.fromisoformat(plan.exported_at)
            if plan.exported_at
            else None,
            people_map=seated,
        )
        await session.commit()
        job_id = cast(int, job.id)
    await _wait_for_import(guild_id, job_id)
    if directory is not None:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            await session.exec(
                update(Initiative).values(join_policy=directory.join_policy.value)
            )
            await session.commit()
    await publish(guild_id, host)
    return guild_id


async def _list(session: AsyncSession, guild: Guild, card: DemoDirectoryCard) -> None:
    """Put the community in the directory with ``card``, and the directory
    on. Staged."""
    row = await app_settings_service.get_app_settings(session)
    row.community_directory_enabled = True
    session.add(row)
    guild.is_community = True
    guild.categories = guilds_service.normalize_categories(
        [category.value for category in card.categories]
    )
    # A listing declares its audience, and the demo's are all ages.
    guild.has_adult_content = False
    session.add(guild)
    await session.flush()


async def delete_pitch(session: AsyncSession, pitch_id: int) -> bool:
    """End the pitch's links and delete its community now. ``False`` when it
    is not a pitch. Raises ``HoldsInForce`` while the platform holds anything
    there, its links already ended. ``session`` is a platform system
    session."""
    if not await is_pitch(session, pitch_id):
        return False
    await session.exec(
        update(DemoLink)
        .where(DemoLink.source_guild_id == pitch_id, DemoLink.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await session.commit()
    pitch = await session.get(Guild, pitch_id)
    if pitch is not None:
        await guild_purge.destroy_now(session, pitch)
    return True


async def _wait_for_import(guild_id: int, job_id: int) -> None:
    """Run the import job here unless a server's import worker claims it
    first, and wait for it either way. Raises unless every entry applied."""
    deadline = asyncio.get_running_loop().time() + IMPORT_TIMEOUT_SECONDS
    while True:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            job = await session.get(ImportJob, job_id)
            if job is None or job.status not in (
                ImportJobStatus.queued,
                ImportJobStatus.running,
            ):
                break
            task = await import_worker.jobs.claim(session, guild_id)
        if task is not None:
            await task
        elif asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"the import into community {guild_id} timed out")
        else:
            await asyncio.sleep(IMPORT_POLL_SECONDS)
    if job is None or job.status != ImportJobStatus.done:
        raise RuntimeError(
            f"the import into community {guild_id} ended "
            f"{job.status if job else 'missing'}: {job.error if job else ''}"
        )
    failed = [
        entry["path"]
        for entry in (job.result or {}).get("entries", [])
        if entry["status"] == "failed"
    ]
    if failed:
        raise RuntimeError(
            f"the import into community {guild_id} left out {', '.join(failed)}"
        )


async def publish(guild_id: int, host: User) -> None:
    """Queue a whole-community export of the pitch, run as the demo host, which
    holds its seat."""
    from app.api.deps import establish_guild_access
    from app.services.export.engine import start_export

    async with cohorts.request_sessionmaker(guild_id)() as session:
        await establish_guild_access(session, host, guild_id, on_behalf=True)
        await start_export(
            session,
            user=host,
            guild_id=guild_id,
            source="community",
            format="zip",
            params={"mode": "backup"},
            allow_job=True,
        )
        await session.commit()


def _published(column: Any) -> SelectOfScalar[Any]:
    """A query for ``column`` of the pitch's newest finished community backup,
    the export a copy imports."""
    return (
        select(column)
        .where(
            ExportJob.source == "community",
            ExportJob.status == ExportJobStatus.done,
            ExportJob.artifact_ref.is_not(None),
            func.coalesce(ExportJob.params.op("->>")("mode"), "backup") == "backup",
        )
        .order_by(ExportJob.created_at.desc())
        .limit(1)
    )


async def newest_export(guild_id: int) -> tuple[str, datetime] | None:
    """Where the pitch's newest finished community backup is stored, and when
    it was taken, or ``None`` when it has none."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        newest = (await session.exec(_published(ExportJob))).first()
    return (
        None if newest is None else (cast(str, newest.artifact_ref), newest.created_at)
    )


async def published_export_id(session: AsyncSession, guild_id: int) -> int | None:
    """The id of the export copies of the community ``guild_id`` import, or
    ``None`` when it is not a pitch or has none. ``session`` is routed into
    the community."""
    async with cohorts.system_session(None) as platform:
        await set_rls_context(platform, Unattributed())
        if not await is_pitch(platform, guild_id):
            return None
    return (await session.exec(_published(ExportJob.id))).first()


async def is_pitch(session: AsyncSession, guild_id: int) -> bool:
    """Whether the community ``guild_id`` is a pitch: made by the demo host,
    and neither a pool community nor a copy. ``session`` is a platform system
    session."""
    host = await accounts.by_handle(session, accounts.HOST_HANDLE)
    guild = await session.get(Guild, guild_id)
    return (
        host is not None
        and guild is not None
        and guild.created_by == host.id
        and await session.get(DemoSandbox, guild_id) is None
    )


async def find_pitches(
    session: AsyncSession, names: Sequence[str]
) -> list[tuple[int, str, datetime]]:
    """The pitches named exactly one of ``names``, as ``(id, name,
    created_at)``, oldest first. ``session`` is a platform system session."""
    host = await accounts.by_handle(session, accounts.HOST_HANDLE)
    if host is None:
        return []
    rows = await session.exec(
        select(Guild.id, Guild.name, Guild.created_at)
        .where(
            Guild.created_by == host.id,
            Guild.name.in_(list(names)),
            Guild.status != CommunityStatus.deleted.value,
            ~exists().where(DemoSandbox.guild_id == Guild.id),
        )
        .order_by(Guild.created_at, Guild.id)
    )
    return [(cast(int, id_), name, created_at) for id_, name, created_at in rows]


async def make_link(
    session: AsyncSession,
    *,
    pitch_id: int,
    role: CommunityRole = CommunityRole.admin,
    lifetime: timedelta | None = LINK_LIFETIME,
    label: str | None = None,
    max_redemptions: int | None = None,
    max_live: int | None = None,
    created_by: int | None = None,
) -> tuple[DemoLink, str]:
    """A new link handing out the pitch ``pitch_id``, lasting ``lifetime`` (for
    good when ``None``), and its token. Only the token's hash is kept, so the
    token is returned once, here. Staged; the caller commits."""
    if role not in LINK_ROLES:
        raise ValueError(f"a link gives member, admin or superadmin, not {role}")
    if not await is_pitch(session, pitch_id):
        raise ValueError(f"community {pitch_id} is not a pitch")
    token = secrets.token_urlsafe(32)
    link = DemoLink(
        token_hash=hash_token(token),
        source_guild_id=pitch_id,
        role=role,
        expires_at=datetime.now(timezone.utc) + lifetime if lifetime else None,
        label=label,
        max_redemptions=max_redemptions,
        max_live=max_live,
        created_by=created_by,
    )
    session.add(link)
    await session.flush()
    return link, token


async def revoke_link(session: AsyncSession, link_id: int) -> bool:
    """End the link now. ``False`` when there is no such link. Staged."""
    link = await session.get(DemoLink, link_id)
    if link is None:
        return False
    link.revoked_at = link.revoked_at or datetime.now(timezone.utc)
    session.add(link)
    return True
