"""Guild-level export sections — what a community owns outside its initiatives.

The per-tool envelopes in ``adapters/`` cover the work done *inside* an
initiative. They do not cover the community itself: its configuration, its tag
vocabulary, its roster, or the plug-ins it installed. Those live in guild-level
tables (``db.tenancy.GUILD_LEVEL_TABLES``) and had no representation in a
backup at all, so a guild that exported and re-imported got its content back
and lost everything that made it that community.

Declared as a registry rather than as a list of calls inside the adapter, for
the reason ``NON_EXPORTABLE_TOOLS`` is an exclusion list: the default is
"a guild-level table is exported", and ``guild_sections_test`` fails until a
new one is either carried by a section here or named in ``EXEMPT`` with a
reason. Remembering to come back to this file is not the mechanism.

Two rules the builders hold to:

* **Secrets never leave.** A row that holds a credential is exempt, and a
  section over a table that holds one selects columns rather than dumping the
  row (``guild_plugins.connection_refs`` is the live example).
* **People are named the way the rest of the app names them.** The roster goes
  through ``GuildMember``/``handle_of``, the same shape every other
  server-generated text uses, so a name reads here exactly as it does
  everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User

# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionContext:
    """What a builder is given: a guild-routed session, who is asking, and the
    manifest's ``skipped`` list to record anything it leaves out.

    A builder that drops something the caller can see appends to ``skipped``
    rather than staying quiet, so the archive states what it does not hold.
    """

    session: AsyncSession
    user: User
    guild_id: int
    skipped: list = field(default_factory=list)


@dataclass(frozen=True)
class GuildSection:
    """One guild-level file in the archive.

    ``build`` returns the payload and the record count, or ``None`` when the
    community has nothing of this kind — an absent section reads as "none",
    which is why an empty one is not written.

    ``scopes`` decides which exports carry the section. A section describing
    the COMMUNITY — its configuration, its roster, what it installed — belongs
    to the community-scoped export. ``tags`` is in both, because the
    vocabulary is part of the content an initiative archive carries: without
    it every tag in that archive arrives with its colour missing.
    """

    key: str
    path: str
    build: Callable[[SectionContext], Awaitable[tuple[dict[str, Any], int] | None]]
    scopes: frozenset[str] = frozenset({"guild"})


async def _build_settings(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """The community's own configuration: the row people edit under Settings,
    plus the guild-level flags that live on the ``guilds`` row itself."""
    from sqlmodel import select

    from app.core.rules import COMMUNITY_RULES, SetBy, SignInRequirement, writers
    from app.models.platform.guild import Guild
    from app.models.tenant.guild_setting import GuildSetting
    from app.services.platform import rules

    guild = await ctx.session.get(Guild, ctx.guild_id)
    if guild is None:
        return None
    setting = (await ctx.session.exec(select(GuildSetting).limit(1))).first()
    stored = (
        await rules.community_values(
            ctx.session, [ctx.guild_id], applied=False, own=True
        )
    )[ctx.guild_id]
    payload: dict[str, Any] = {
        "type": "guild-settings",
        "schema_version": 1,
        "name": guild.name,
        "description": guild.description,
        "is_community": guild.is_community,
        "categories": list(guild.categories or []),
        "location": guild.location,
        "has_adult_content": guild.has_adult_content,
        # Every rule the community wrote itself; a sign-in requirement in the
        # shape the settings page reads it. What the deployment sets, its plan
        # and its surfaces among it, stays behind.
        **{
            key: {
                "policy": value.policy,
                "provider_id": value.provider_id,
                "require_methods": sorted(m.value for m in value.methods),
            }
            if isinstance(value, SignInRequirement)
            else value
            for key, value in stored.items()
            if SetBy.community in writers(COMMUNITY_RULES[key])
        },
        "banner": dict(guild.banner or {}),
        "retention_days": setting.retention_days if setting else None,
    }
    return payload, 1


async def _build_tags(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """The tag vocabulary. Envelopes reference tags by NAME, so without this
    the definitions — colour, and the fact that a tag existed at all before
    anything was tagged with it — do not survive a round trip."""
    from sqlmodel import select

    from app.models.tenant.tag import Tag

    rows = list(await ctx.session.exec(select(Tag).order_by(Tag.name.asc())))
    if not rows:
        return None
    payload = {
        "type": "guild-tags",
        "schema_version": 1,
        "tags": [
            {"name": tag.name, "color": tag.color, "created_at": _iso(tag.created_at)}
            for tag in rows
        ],
    }
    return payload, len(rows)


async def _build_members(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """Who was in the community, at what guild role, and whether their
    personal API keys reached it.

    Named by handle rather than by id: an id means nothing in the instance the
    archive is restored into, while a handle is the identifier that reads the
    same everywhere (it is how ``ManifestPerson`` already inventories comment
    authors). The numeric id rides along as the same-instance fast path.

    People come from ``GuildMember``, the projection already narrowed to the
    routed guild's members, rather than from the unnarrowed one filtered by a
    list of ids — so the roster is this community's by construction.
    """
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.models.platform.guild import GuildMembership
    from app.models.platform.rule import CommunityRule
    from app.models.platform.user_profile_view import GuildMember

    memberships = list(
        await ctx.session.exec(
            select(GuildMembership)
            .where(GuildMembership.guild_id == ctx.guild_id)
            .order_by(GuildMembership.user_id.asc())
        )
    )
    if not memberships:
        return None
    profiles = {
        profile.id: profile for profile in await ctx.session.exec(select(GuildMember))
    }
    # The members whose keys the seat turned off; everybody else's reach it.
    keys_off = set(
        await ctx.session.exec(
            select(CommunityRule.user_id).where(
                CommunityRule.guild_id == ctx.guild_id,
                CommunityRule.key == "api_keys",
                CommunityRule.user_id.is_not(None),  # type: ignore[union-attr]
                CommunityRule.enabled.is_(False),  # type: ignore[union-attr]
            )
        )
    )
    members = []
    for membership in memberships:
        profile = profiles.get(membership.user_id)
        members.append(
            {
                "user_id": membership.user_id,
                "handle": handle_of(profile) if profile else None,
                "name": membership.display_name,
                "role": _enum_value(membership.role),
                "api_keys_allowed": membership.user_id not in keys_off,
                "joined_at": _iso(getattr(membership, "created_at", None)),
            }
        )
    payload = {"type": "guild-members", "schema_version": 1, "members": members}
    return payload, len(members)


async def _build_plugins(ctx: SectionContext) -> tuple[dict[str, Any], int] | None:
    """Plug-ins the community installed — built-in ones only.

    A plug-in published by anybody but this build is not ours to put in a file:
    its definition belongs to its publisher, and restoring it elsewhere means
    installing it there from the catalog, not unpacking a copy. Third-party
    installs are recorded in the manifest's ``skipped`` list instead, so the
    archive says they existed.

    Columns are selected rather than dumped: ``secret_fields`` and
    ``connection_refs`` never appear, and the secret values are in
    ``guild_plugin_secrets``, which is exempt.
    """
    from sqlmodel import select

    from app.models.tenant.guild_plugin import GuildPlugin
    from app.services.export.provenance import builtin_listing_uids

    from app.schemas.tenant.backup_export import ManifestSkipped
    from app.services.export.provenance import THIRD_PARTY_REASON

    rows = list(
        await ctx.session.exec(select(GuildPlugin).order_by(GuildPlugin.id.asc()))
    )
    if not rows:
        return None
    builtin = await builtin_listing_uids(
        ctx.session, [row.listing_uid for row in rows if row.listing_uid]
    )
    kept = []
    for row in rows:
        if row.listing_uid in builtin:
            kept.append(row)
        else:
            ctx.skipped.append(
                ManifestSkipped(
                    tool="plugin",
                    entity_id=row.id,
                    title=row.name,
                    reason=THIRD_PARTY_REASON,
                )
            )
    if not kept:
        return None
    from app.services.tenant.guild_plugins import placements_by_install

    placements = await placements_by_install(ctx.session, [row.id for row in kept])
    payload = {
        "type": "guild-plugins",
        "schema_version": 2,
        "plugins": [
            {
                "listing_uid": row.listing_uid,
                "listing_version": row.listing_version,
                "plugin_kind": row.plugin_kind,
                "name": row.name,
                "enabled": row.enabled,
                "auto_update": row.auto_update,
                "config": dict(row.config or {}),
                "placements": [
                    {
                        "initiative_id": placement.initiative_id,
                        "role_ids": list(placement.role_ids or []),
                    }
                    for placement in placements.get(row.id, [])
                ],
            }
            for row in kept
        ],
    }
    return payload, len(kept)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _enum_value(value) -> Any:
    return getattr(value, "value", value)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

GUILD_SECTIONS: tuple[GuildSection, ...] = (
    GuildSection("settings", "guild/settings.json", _build_settings),
    GuildSection(
        "tags",
        "guild/tags.json",
        _build_tags,
        scopes=frozenset({"guild", "initiative"}),
    ),
    GuildSection("members", "guild/members.json", _build_members),
    GuildSection("plugins", "guild/plugins.json", _build_plugins),
)


def sections_for(scope_kind: str) -> tuple[GuildSection, ...]:
    """The sections an export at this scope may carry."""
    return tuple(s for s in GUILD_SECTIONS if scope_kind in s.scopes)


# Guild-level table -> the section key that carries it. Checked against
# ``db.tenancy.GUILD_LEVEL_TABLES`` (an independent source) by
# ``guild_sections_test``.
SECTION_TABLES: dict[str, str] = {
    "guild_settings": "settings",
    "tags": "tags",
    "guild_plugins": "plugins",
    # Each install's placements ride inside its entry in the plugins section.
    "plugin_placements": "plugins",
    # Carried per-initiative rather than at the guild root: an initiative's
    # roster and role set belong beside its content, not in one flat file.
    "initiatives": "initiatives",
    "initiative_members": "initiatives",
    "initiative_roles": "initiatives",
    "initiative_rules": "initiatives",
}

# Guild-level tables deliberately NOT exported, and why. A reason is required:
# it is what a reviewer reads instead of guessing whether the omission was a
# decision or an oversight.
EXEMPT: dict[str, str] = {
    # Credentials. An archive is a file that leaves the deployment.
    "guild_ai_connections": "credentials",
    "guild_ai_connection_keys": "credentials",
    "guild_plugin_secrets": "credentials",
    "guild_plugin_user_connections": "credentials",
    "plugin_connection_secrets": "credentials",
    "plugin_member_consents": "credentials",
    # Operational ledgers about the app's own work. Restoring them would
    # describe a history that did not happen in the instance reading them.
    "data_jobs": "operational",
    "webhook_deliveries": "operational",
    "plugin_hook_deliveries": "operational",
    "plugin_schedule_runs": "operational",
    "timer_marks": "operational",
    "subscription_progress": "operational",
    # In-flight workflow rather than owned content: a request to join is a
    # question waiting on somebody in THIS instance.
    "initiative_join_requests": "in_flight",
    # A file still arriving, which only this instance's storage holds.
    "pending_uploads": "in_flight",
    # The platform's record of what it holds here. Not the community's to
    # read, so not the community's to carry out.
    "content_holds": "platform",
}

__all__ = [
    "GUILD_SECTIONS",
    "sections_for",
    "GuildSection",
    "SectionContext",
    "SECTION_TABLES",
    "EXEMPT",
]
