"""``initiative-post`` importer: one bulletin-board notice with its tags and
the question it asks.

Neither the pin nor the schedule is carried by the envelope, for the same
reason: both said what this notice meant on the board it came from. An imported
post arrives live, in the feed by its own date, like anything else somebody
just wrote — and its poll arrives open and unanswered, for the same reason the
sharing is not carried: the people who answered it are not the people here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll, PostPollOption
from app.schemas.tenant.import_envelopes import PostEnvelope
from app.services.import_engine.common import (
    load_initiative_member_handles,
    unique_name_in_initiative,
)
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.mentions import place_mentions
from app.services.import_engine.people import PeopleMap
from app.services.import_engine.references import note_or_settle

#: What ``posts.name`` holds, and how much of it to leave for the " (2)" that
#: ``unique_name_in_initiative`` may append when the board already has this headline.
_MAX_NAME = 255
_NAME_SUFFIX_ROOM = 8


class PostImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.post)
    permission = PermissionKey.create_posts

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(PostEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        return 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: PostEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model

        # The column holds 255. A headline over it would fail at flush and take
        # the whole entry down with it, so it is trimmed and reported —
        # `unique_name_in_initiative` may add a suffix, so trim first and leave it room.
        warnings: list[str] = []
        name = env.name
        if len(name) > _MAX_NAME:
            name = name[: _MAX_NAME - _NAME_SUFFIX_ROOM].rstrip()
            warnings.append(f"Headline shortened to fit: {name!r}")

        body = place_mentions(
            env.body or {},
            env.mention_handles,
            people=context.people if context is not None else PeopleMap(),
            member_handles=(
                await load_initiative_member_handles(
                    session, initiative_id=target_initiative.id
                )
                if env.mention_handles
                else {}
            ),
        )

        post = Post(
            name=await unique_name_in_initiative(
                session, Post, target_initiative.id, name
            ),
            body=body,
            initiative_id=target_initiative.id,
            created_by=importer.id,
            # A restored notice is live on arrival. The schedule is not carried
            # for the same reason the pin is not: it said when this notice
            # mattered on the board it came from, and re-running it here would
            # hide an import until a date that has nothing to do with this one.
            published_at=datetime.now(UTC),
        )
        session.add(post)
        await session.flush()
        post.body = note_or_settle(context, SearchEntityType.post, post.id, post.body)

        await grant_ownership(
            session,
            tool=Tool.post,
            entity_id=post.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        if env.poll is not None:
            session.add(
                PostPoll(
                    post_id=post.id,
                    question=(env.poll.question or "").strip() or None,
                    allows_multiple=env.poll.allows_multiple,
                    is_anonymous=env.poll.is_anonymous,
                    hide_results=env.poll.hide_results,
                    options=[
                        PostPollOption(position=index, text=text)
                        for index, text in enumerate(env.poll.options)
                    ],
                )
            )

        tags = TagRestore(session)
        await tags.attach(post, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(post, env.properties)
        return EnvelopeImportResult(
            entity_id=post.id,
            entity_title=post.name,
            created={
                Tool.post.plural: 1,
                "tags": tags.created,
                "properties": props.created,
                **({"polls": 1} if env.poll is not None else {}),
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=await props.settle(post),
            warnings=warnings,
        )
