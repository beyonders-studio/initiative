"""The one seam for "run this test AS role X": an authenticated test identity
with explicit platform and guild roles, plus optional initiative/project
scaffolding.

The two role dimensions are orthogonal (platform-roles design §7):

* **Platform role** — the tier the public/platform request path assumes
  (``platform_<users.role>``). Defaults to ``owner`` for public-path actors
  (most privileged, so role-agnostic tests run unblocked) and to ``member``
  for guild-path actors — guild access must never depend on platform tier,
  and defaulting low makes the suite prove that continuously.
* **Guild role** — when ``guild_role`` (or ``guild``) is given, the actor gets
  a provisioned guild (or joins the one passed) with that ``CommunityRole``;
  requests route through ``/c/{community_id}`` and assume ``guild_<id>``.

Usage (via the ``acting_user`` fixture):

    a = await acting_user()                                   # platform owner
    a = await acting_user("support")                          # tier ceilings
    a = await acting_user(guild_role=CommunityRole.admin,
                          initiative=True, project=True)      # full workspace
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild,
                          initiative=a.initiative, initiative_role="member")
    await client.get(a.g("/projects/"), headers=a.headers)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole, Guild, GuildMembership
from app.models.platform.user import User, UserRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
    get_auth_headers,
)

API = "/api/v1"


def guild_url(guild_id: int, path: str = "/") -> str:
    """Guild-scoped API URL: ``guild_url(7, "/projects/")`` →
    ``/api/v1/c/7/projects/``."""
    return f"{API}/c/{guild_id}{path}"


@dataclass
class Actor:
    """An authenticated test identity and the workspace it acts in."""

    user: User
    headers: dict[str, str]
    guild: Guild | None = None
    membership: GuildMembership | None = None
    initiative: Initiative | None = None
    project: Project | None = None

    def g(self, path: str = "/") -> str:
        """``guild_url`` for this actor's guild."""
        if self.guild is None:
            raise ValueError("actor has no guild; pass guild_role=")
        return guild_url(self.guild.id, path)


async def make_actor(
    session: AsyncSession,
    role: UserRole | str | None = None,
    *,
    guild_role: CommunityRole | str | None = None,
    guild: Guild | None = None,
    initiative: Initiative | bool | None = None,
    initiative_role: str = "project_manager",
    project: Project | bool | None = None,
    **overrides: Any,
) -> Actor:
    """Build an :class:`Actor`. See the module docstring for semantics.

    ``initiative=True`` creates one with the actor as creator (built-in PM);
    pass an existing ``Initiative`` to join it with ``initiative_role``.
    ``project=True`` creates one owned by the actor inside the initiative;
    pass an existing ``Project`` to reference it without any grant.
    ``**overrides`` go to ``create_user`` (e.g. ``email=``, ``username=``).
    """
    if guild is not None and guild_role is None:
        guild_role = CommunityRole.member
    if role is None:
        role = UserRole.member if guild_role is not None else UserRole.owner
    if isinstance(role, str):
        role = UserRole(role)

    user = await create_user(session, role=role, **overrides)
    headers = get_auth_headers(user)

    if guild_role is None:
        if initiative is not None or project is not None:
            raise ValueError("initiative/project require a guild_role")
        return Actor(user=user, headers=headers)

    if isinstance(guild_role, str):
        guild_role = CommunityRole(guild_role)
    in_guild = guild if guild is not None else await create_guild(session)
    membership = await create_guild_membership(
        session, user=user, guild=in_guild, role=guild_role
    )

    in_initiative: Initiative | None = None
    if initiative is True:
        if initiative_role != "project_manager":
            raise ValueError(
                "initiative=True makes the actor the creator (PM); pass an "
                "existing initiative to join it with initiative_role="
            )
        in_initiative = await create_initiative(session, in_guild, user)
    elif isinstance(initiative, Initiative):
        in_initiative = initiative
        await create_initiative_member(
            session, initiative, user, role_name=initiative_role
        )

    in_project: Project | None = None
    if project is True:
        if in_initiative is None:
            raise ValueError("project=True requires initiative")
        in_project = await create_project(session, in_initiative, user)
    elif isinstance(project, Project):
        in_project = project

    return Actor(
        user=user,
        headers=headers,
        guild=in_guild,
        membership=membership,
        initiative=in_initiative,
        project=in_project,
    )
