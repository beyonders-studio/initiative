"""What every area of the dev seed shares: the clock, the community being
seeded, and the helpers each tool's rows are built with."""

from __future__ import annotations

import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageEnhance
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant._mixins import ArchiveMixin
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import CounterGroup
from app.models.tenant.file import File
from app.models.tenant.initiative import Initiative, InitiativeRoleModel
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import Tag
from app.models.tenant.task import Task
from app.services.tenant import tags as tags_service

#: One "now" for the whole run, so every relative date in it agrees.
NOW = datetime.now(timezone.utc)

#: The photos every seeded picture is cut from: the front page's own.
PHOTOS = Path(__file__).resolve().parents[2] / "frontend" / "public" / "homepage"


def days_ago(days: int) -> datetime:
    """How a seeded picture is dated, so a wall has months for the timeline
    rail to scrub through rather than everything arriving at once."""
    return NOW - timedelta(days=days)


@dataclass
class Community:
    """One community being seeded, and what its later steps need from its
    earlier ones.

    ``key`` picks this community's rows out of each area's tables. Initiatives
    and their member roles are keyed by the seed's own short names; everything
    else by the title the tables use for it.
    """

    key: str
    session: AsyncSession
    ids: dict[str, list]
    users: dict[str, User]
    guild: Guild
    initiatives: dict[str, Initiative] = field(default_factory=dict)
    member_roles: dict[str, InitiativeRoleModel] = field(default_factory=dict)
    tags: dict[str, Tag] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    files: dict[str, File] = field(default_factory=dict)
    counter_groups: dict[str, CounterGroup] = field(default_factory=dict)
    events: dict[str, CalendarEvent] = field(default_factory=dict)
    #: Rows to archive, and the date to stamp, once the community is filled.
    archives: list[tuple[ArchiveMixin, datetime]] = field(default_factory=list)


def share(
    c: Community,
    tool: Tool,
    row: SQLModel,
    owner: User,
    *,
    writers: Iterable[str] = (),
    readers: Iterable[str] = (),
    roles: Iterable[tuple[str, ResourceAccessLevel]] = (),
    general: ResourceAccessLevel | None = None,
) -> None:
    """The owner grant, and whatever sharing a table row asks for.

    ``writers``/``readers`` are people by name, ``roles`` is ``(initiative key,
    level)`` for that initiative's member role, and ``general`` is the
    all-initiative-members grant. None of them leaves the row private.
    """

    def grant(level: ResourceAccessLevel, **grantee: object) -> None:
        c.session.add(
            ResourceGrant(
                resource_type=tool.value,
                resource_id=row.id,
                initiative_id=row.initiative_id,
                level=level,
                **grantee,
            )
        )

    grant(ResourceAccessLevel.owner, user_id=owner.id)
    for names, level in (
        (writers, ResourceAccessLevel.write),
        (readers, ResourceAccessLevel.read),
    ):
        for name in names:
            if c.users[name].id != owner.id:
                grant(level, user_id=c.users[name].id)
    for key, level in roles:
        grant(level, role_id=c.member_roles[key].id)
    if general is not None:
        grant(general, all_initiative_members=True)


def tag(c: Community, row: SQLModel, names: Iterable[str]) -> None:
    """Label ``row`` with the community's tags, as the edges the app stores."""
    spec = tags_service.spec_for(row)
    for name in names:
        c.session.add(tags_service.tag_edge(spec, row.id, c.tags[name].id))


# --- Lexical bodies ---------------------------------------------------------


def para(text: str) -> dict:
    """One paragraph, as the editor serializes one."""
    return {"children": [{"text": text, "type": "text"}], "type": "paragraph"}


def heading(text: str, level: int = 2) -> dict:
    """One heading. The contents list in the sidebar is built from these."""
    return {
        "children": [{"text": text, "type": "text"}],
        "type": "heading",
        "tag": f"h{level}",
    }


def lexical(children: list[dict]) -> dict:
    """An editor document holding ``children``."""
    return {"root": {"children": children, "type": "root"}}


def chip(entity_type: str, entity_id: int, text: str) -> dict:
    """A live smart chip, as the editor serializes one.

    Only the three fields ``EntityMentionNode.importJSON`` reads. A chip shows
    a fact ABOUT the thing it names and keeps showing the current one.
    """
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": entity_type,
        "entityId": entity_id,
        "text": text,
    }


def photo(
    name: str, width: int, height: int, *, shade: int = 0, max_bytes: int | None = None
) -> bytes:
    """One of the front page's photos as a WebP, cut from its middle to
    ``width``:``height`` and no larger than that, so a picture keeps its
    proportions without being made bigger than the photo is. Each ``shade``
    darkens it a step, for an earlier rendition of the same picture. Given
    ``max_bytes``, it is saved at whatever quality fits."""
    image = Image.open(PHOTOS / f"{name}.webp").convert("RGB")
    scale = min(image.width / width, image.height / height)
    cut_width, cut_height = round(width * scale), round(height * scale)
    left = (image.width - cut_width) // 2
    top = (image.height - cut_height) // 2
    image = image.crop((left, top, left + cut_width, top + cut_height))
    if cut_width > width:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    if shade:
        image = ImageEnhance.Brightness(image).enhance(1 - 0.15 * shade)
    for quality in range(80, 0, -10):
        out = io.BytesIO()
        image.save(out, "WEBP", quality=quality)
        if max_bytes is None or out.tell() <= max_bytes:
            break
    return out.getvalue()
