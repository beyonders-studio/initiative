"""Post source adapter: the envelope (json) every tool writes.

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

from typing import Any

from sqlalchemy import ColumnElement
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import ToolRecord
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.post import Post, is_published_clause
from app.schemas.tenant.import_envelopes import PostPollEnvelope
from app.services.export.adapters._common import BuildContext, ToolExportAdapter
from app.services.export.envelope import record
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

    def in_initiative(
        self, record: ToolRecord, initiative_id: int, /
    ) -> list[ColumnElement[bool]]:
        """Only published posts: a draft is in no export."""
        return [*super().in_initiative(record, initiative_id), is_published_clause()]

    def fields(self, post: Post, ctx: BuildContext, /) -> dict[str, Any]:
        """The poll's choices, as their text in the order they are offered."""
        poll = post.poll
        if poll is None:
            return {"poll": None}
        options = sorted(poll.options or [], key=lambda o: (o.position, o.id))
        return {
            "poll": record(
                PostPollEnvelope, poll, options=[option.text for option in options]
            )
        }
