"""Post source adapter: the importable backup envelope (json).

A post's body is a Lexical editor state, so the envelope carries it whole and
an import rebuilds the notice exactly — the same thing the file envelope
does with ``content``. Rendered formats (md/pdf/docx) go through the Lexical
converter and are not offered yet; a notice exports as the thing it is.

What the envelope deliberately drops is the pin. A pin is a fact about the
board — "this is what matters here right now" — not about the notice, so
carrying it across would put an imported post above the posts already on
somebody else's board.

A poll crosses as the **question**, never the answers. A ballot is one person
in one community saying something, and the ids naming them mean nothing in the
guild a backup is restored into — the same reason the sharing is not carried.
So does its close time, for the reason the pin is dropped: it said when the
question stopped mattering on the board it came from.

A notice that has not gone up is not exported at all — see
``PostAdapter.in_initiative``. An export is a record of what a board has
said, and a scheduled draft has said nothing yet.

Access rule: READ on the post (exporting is a formatted read), enforced by the
``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.post import Post, is_published_clause
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties
from app.services.permissions import EXPORT_ACCESS


class PostAdapter(ToolExportAdapter):
    tool = Tool.post

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        post_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Post:
        from app.services.tenant import metadata as metadata_service
        from app.services.tenant import tags as tags_service

        post = await super().fetch(session, user, guild_id, post_id, access=access)
        await tags_service.annotate_tags(session, [post])
        await metadata_service.annotate_properties(session, [post])
        return post

    def in_initiative(self, initiative_id: int, /) -> list[ColumnElement[bool]]:
        """Only published posts: a draft is in no export."""
        return [*super().in_initiative(initiative_id), is_published_clause()]

    def item(self, post: Post, ctx: BuildContext, /) -> RenderItem:
        return build_post_item(post, ctx.format, ctx.now)


def build_post_item(post: Post, format: str, now: datetime) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=envelope_key(Tool.post, post.name, now.strftime("%Y-%m-%d")),
        data=_envelope(post),
    )


def _envelope(post: Post) -> dict[str, Any]:
    return {
        "type": tool_envelope_type(Tool.post),
        "schema_version": 1,
        "name": post.name,
        "body": post.body or {},
        "tags": sorted(tag.name for tag in post.tags or []),
        "properties": exported_properties(post),
        "poll": _poll_envelope(post),
    }


def _poll_envelope(post: Post) -> dict[str, Any] | None:
    poll = getattr(post, "poll", None)
    if poll is None:
        return None
    return {
        "question": poll.question,
        "options": [
            option.text
            for option in sorted(poll.options or [], key=lambda o: (o.position, o.id))
        ],
        "allows_multiple": poll.allows_multiple,
        "is_anonymous": poll.is_anonymous,
        "hide_results": poll.hide_results,
    }
