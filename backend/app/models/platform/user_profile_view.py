"""The projections of ``public.users`` the request path reads.

``public.users`` itself is not readable on the request path. Two views over it
are, each owned by ``app_profile_reader`` — a NOLOGIN role holding a
column-scoped SELECT on the table — so what is public is decided by the
catalog rather than by whoever writes the next query:

* ``public.user_profiles`` (migration 0214) — the eight columns a profile is,
  read by the cross-guild profile page on a ``platform_base`` session.
* ``public.guild_member_profiles`` — those plus ``display_name``, read by
  every guild-routed session: the name the member set for the guild the
  request is routed into (``guild_memberships.display_name``, migrations 0438
  and 0439), ``NULL`` where they set none, when the handle renders.

Which columns those are lives in ``app.db.user_columns``.

Both tables live in their own ``MetaData``, deliberately: a view is not a
table, and putting one in ``SQLModel.metadata`` would make the table
classification and drift checks treat it as one and try to keep it in step with
a model.

``MemberProfile`` is the mapped class over the guild view. It is what every
tenant relationship that used to point at ``User`` points at now
(``Task.assignees``, ``InitiativeMember.user``, ``Comment.author``, …), so
loading a person from guild content yields a person, not an account. It is
mapped imperatively into SQLModel's own registry so those relationships can
still name it as a string, while its table stays out of ``SQLModel.metadata``.
"""

from datetime import datetime

from sqlalchemy import Column, MetaData, String, Table
from sqlmodel import SQLModel

from app.db.user_columns import PUBLIC_PROFILE_COLUMNS
from app.models.platform.user import User, UserStatus

#: Not ``SQLModel.metadata`` — see the module docstring.
metadata = MetaData()


def _profile_view(name: str, *extra: Column) -> Table:
    """A view over ``public.users``: the profile columns as the table declares
    them, then ``extra``."""
    return Table(
        name,
        metadata,
        *(
            Column(column.name, column.type, primary_key=column.primary_key)
            for column in (User.__table__.c[name] for name in PUBLIC_PROFILE_COLUMNS)
        ),
        *extra,
        schema="public",
    )


user_profiles = _profile_view("user_profiles")

guild_member_profiles = _profile_view(
    "guild_member_profiles", Column("display_name", String)
)


#: The same projection, narrowed to the guild a request is routed into
#: (migration 0244). What the query surface names, because a statement that
#: named the unnarrowed one would list every account on the deployment.
current_guild_members = _profile_view(
    "current_guild_members",
    #: The name to group by: the real one where the guild renders it, and the
    #: handle where it does not.
    Column("display_name", String),
)


class MemberProfile:
    """A person, as guild content refers to them.

    Everything a roster, a picker, a mention, an assignee chip or a comment
    byline renders, and nothing else: the shapes in ``app.schemas`` that name a
    person (``UserPublic``, ``UserSummary``, ``CommentAuthor``,
    ``ReactionUser``, ``TaskAssigneeSummary``) validate straight off one of
    these.

    Reading an account's own settings — preferences, address, locale — is the
    account holder's own business or the system engine's, and goes through
    ``User`` on a session that may.
    """

    id: int
    username: str
    discriminator: int
    display_name: str | None
    avatar_url: str | None
    status: UserStatus
    custom_status: dict
    profile_decorations: dict
    created_at: datetime

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MemberProfile {self.username}#{self.discriminator:04d}>"


# Into SQLModel's registry rather than a private one, so a relationship on a
# SQLModel table can name ``"MemberProfile"`` the way it named ``"User"``.
SQLModel._sa_registry.map_imperatively(MemberProfile, guild_member_profiles)


class GuildMember:
    """A person, as somebody querying this guild's data finds them.

    The same columns :class:`MemberProfile` has, from the view that narrows
    them to this guild's members — plus the one name a query groups by. It is
    mapped only so the field registry can read its columns off it; nothing
    relates to it, and nothing loads it by id.
    """

    id: int
    username: str
    discriminator: int
    avatar_url: str | None
    status: UserStatus
    custom_status: dict
    profile_decorations: dict
    created_at: datetime
    display_name: str

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<GuildMember {self.username}#{self.discriminator:04d}>"


SQLModel._sa_registry.map_imperatively(GuildMember, current_guild_members)
