"""Post endpoints — an initiative's bulletin board.

Creation is gated at the initiative level (posts_enabled + create_posts);
everything after that flows from the post's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Two things here are the board's own rather than the generic tool shape:

* **Order.** The default list order is the board — live pins on top, then
  newest first — rendered by ``posts_service.board_order()`` so nothing that
  shows a board can disagree about it. Passing ``sort_by`` opts out into the
  ordinary tool sort, which is what the guild-wide table needs.
* **Page size.** A board renders its notices, bodies and all, so the list
  returns whole posts and pages in fives rather than the hundreds every other
  tool list takes. Each body is a Lexical state the client mounts an editor
  for, and that is the cost this cap protects: the board scrolls on rather
  than paging, so a page is what it fetches ahead, not what somebody has to
  look at.
* **Pinning.** Lifting a notice above everyone else's is initiative management
  authority, not write access on the post, so ``PUT /{id}/pin`` asks for guild
  admin or an initiative manager rather than the post's own DAC. Its author
  can edit and delete it either way.
* **Publication.** A post with a ``scheduled_for`` in the future is a draft: it
  is reachable only by the people who could edit it, appears in no board, count
  or search result, and nobody has been told about it. The publication worker
  (``services/tenant/post_publication.py``) stamps ``published_at`` when its
  time comes and announces it then. Posting without a schedule stamps it here
  and announces before the commit, so the notice and the notices about it land
  together.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.messages import PostMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.post import Post, board_time
from app.models.tenant.post_poll import PostPoll
from app.schemas.tenant.post import (
    PostCreate,
    PostReadMarks,
    PostReadReceipt,
    PostReaders,
    PostPinUpdate,
    PostRead,
    PostReactionSettings,
    PostUpdate,
    post_body_too_long,
    post_reader,
)
from app.schemas.tenant.tool import serialize_tool
from app.schemas.tenant.post_poll import (
    PollVoteWrite,
    PollVoters,
    PollOptionVoters,
    PollWrite,
    poll_voter,
    serialize_poll,
)
from app.schemas.tenant.timeline import TimelineResponse
from app.services import notifications as notifications_service
from app.services import rls as rls_service
from app.services.notifications import PluginAuthor
from app.core.search import SearchEntityType
from app.services.tenant import archive as archive_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import comments as comments_service
from app.services.tenant import required_fields
from app.services.tenant import content_references
from app.services.tenant import post_polls as post_polls_service
from app.services.tenant import post_publication
from app.services.tenant import posts as posts_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant import timeline as timeline_service
from app.services.tenant import tool_listing
from app.services.tenant.relationships import Endpoint

#: How many notices a board hands over at once. A post carries its body and
#: the client mounts an editor per body, so this is deliberately far below the
#: 100 every other tool list defaults to — and small enough that the board can
#: fetch the next one as somebody reaches the bottom rather than making them
#: ask. The ceiling below is for the surfaces that page rather than scroll.
BOARD_PAGE_SIZE = 5
MAX_BOARD_PAGE_SIZE = 50

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the posts scopes. Pinning is an
#: edit of the board, so it asks the write scope.
PostsRead = Annotated[ActorContext, Depends(plugin_scope("posts:read"))]
PostsWrite = Annotated[ActorContext, Depends(plugin_scope("posts:write"))]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validated_body(body: dict | None) -> dict:
    """A notice's body, or a 422 saying it is too long.

    The rule itself lives with the schema (``post_body_too_long``) because an
    import applies the same one; this only maps it to a status code.
    """
    clean = body or {}
    if post_body_too_long(clean):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.BODY_TOO_LONG,
        )
    return clean


def _validated_poll(poll_in: PollWrite) -> PollWrite:
    """A poll, or a 422 saying why it is not one.

    How many choices there may be and how long each one is stay with the
    schema — they are shape, and an import is held to the same shape. The two
    rules here are the ones a person can trip over while typing, so each
    answers with a code the composer can put into words rather than a
    validation error nobody can read.
    """
    if poll_in.closes_at is not None and poll_in.closes_at <= datetime.now(
        timezone.utc
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.POLL_CLOSES_IN_PAST,
        )
    choices = [option.text.strip().casefold() for option in poll_in.options]
    if len(set(choices)) != len(choices):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.POLL_DUPLICATE_CHOICE,
        )
    return poll_in


def _poll_of(post: Post) -> PostPoll:
    """This notice's poll, or a 404. A post without one is not an error until
    somebody asks for the poll specifically."""
    poll = post.poll
    if poll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PostMessages.POLL_NOT_FOUND,
        )
    return poll


async def _announce(
    session: RLSSessionDep,
    post: Post,
    author: User | PluginAuthor,
    guild_context: ActorContext,
) -> None:
    """Tell the notice's audience it is up.

    Needs the sharing and the initiative roster loaded, which the row written a
    moment ago does not have — so it is re-read through the post loader before
    the fan-out reads its grants. The session does not autoflush, so the write
    that made it publishable has to reach the database first: without that the
    re-read would replace the pending row with the one still on disk.
    """
    await session.flush()
    hydrated = await posts_service.get_post(session, post.id, populate_existing=True)
    if hydrated is None:  # pragma: no cover — written in this transaction
        return
    await post_publication.announce_post(session, hydrated, author=author)


async def annotate_post_rows(
    session: RLSSessionDep,
    rows: list[Post],
    *,
    user_id: int | None,
) -> None:
    """Everything a post row carries beyond its columns, one grouped query each
    for the page: its tags, properties, comment count, reactions, read state and
    poll tallies.

    An installed plug-in (``user_id`` ``None``) keeps no read markers or ballots
    and reacts to nothing, so a post it reads carries only the comment count;
    the rest stay at their empty defaults.
    """
    await tags_service.annotate_tags(session, rows)
    await metadata_service.annotate_properties(session, rows)
    await comments_service.annotate_comment_counts(session, rows, column="post_id")
    if user_id is None:
        return
    await posts_service.attach_reactions(session, *rows)
    await posts_service.annotate_read_state(session, rows, user_id=user_id)
    await posts_service.annotate_read_counts(session, rows)
    await post_polls_service.annotate_poll_state(session, rows, user_id=user_id)


async def read_after_write(
    session: RLSSessionDep,
    post_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> PostRead:
    """The notice a write answers with: re-read after the commit and annotated
    the way a read is — count, chips, tallies and read state.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    post = await posts_service.get_post(session, post_id, populate_existing=True)
    if not post:
        raise Tool.post.not_found()
    return await _post_read(session, post, guild_context)


async def _post_read(
    session: AsyncSession, post: Post, guild_context: ActorContext
) -> PostRead:
    """One notice as its own read answers it: annotated as a read is."""
    await annotate_post_rows(session, [post], user_id=guild_context.user_id)
    return serialize_tool(
        PostRead, post, user_id=guild_context.user_id, context=guild_context
    )


def board_conditions(
    user_id: int | None,
    *,
    context: ActorContext,
    initiative_id: Optional[int] = None,
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
    unread: bool = False,
    archived: Optional[bool] = None,
) -> list:
    """Which notices this reader may see on a board — the whole rule, once.

    The feed and the timeline rail beside it are two views of one set, and a
    rail that counted a different set would offer months with nothing in them
    (or, worse, hide months that do). So the gates are built here and both
    routes take them: the guild, the feature switch, sharing and the filters
    (:func:`tool_listing.base_conditions`), the archive state, then
    publication — a notice scheduled for later is on the board only for the
    people who could edit it. Property filters are not among them: every list
    applies those itself (``metadata_service.property_filter_clauses``), and
    the timeline applies the same.

    An installed plug-in (``user_id`` ``None``) keeps no read markers, so ``unread``
    narrows nothing for it.
    """
    conditions = tool_listing.base_conditions(
        Tool.post,
        Post,
        user_id,
        context=context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
    )
    conditions.append(archive_service.archive_filter_clause(Post, archived))
    if unread and user_id is not None:
        conditions.append(posts_service.unread_clause(user_id))
    return conditions


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


# Declared before /{post_id} so the literal path wins the match.
@router.get("/timeline", response_model=TimelineResponse)
async def get_post_timeline(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tag_ids: Optional[List[int]] = Query(default=None),
    property_filters: Optional[str] = Query(
        default=None,
        description="The feed's property-value filters, JSON-encoded as it takes them.",
    ),
    unread: bool = Query(default=False),
    archived: Optional[bool] = Query(
        default=None, description=archive_service.ARCHIVED_QUERY_DESCRIPTION
    ),
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA zone the month boundaries are cut in, e.g. Pacific/Auckland. "
            "A month is a boundary in somebody's day, so a reader gets their "
            "own. Defaults to UTC."
        ),
    ),
) -> TimelineResponse:
    """The months this board has notices in, newest first.

    What the timeline rail is drawn from: one row per month, how many notices
    fall in it, and the instant to jump to. It takes the SAME filters the feed
    does, because the rail is a picture of the feed as it currently stands —
    with the unread filter on, a month that is fully read has nothing to offer
    and should not be a stop on the rail.

    Scoped through :func:`board_conditions`, the same gates the list applies, so
    the rail can never show a month whose notices the reader cannot open.
    """
    scope = board_conditions(
        current_user.id,
        context=guild_context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
        unread=unread,
        archived=archived,
    )
    # The feed's property filters, as every list applies them.
    scope += await metadata_service.property_filter_clauses(
        session, Tool.post.value, property_filters, names_people=True
    )
    return TimelineResponse(
        buckets=await timeline_service.month_buckets(
            session, date_expr=board_time(), conditions=scope, tz=tz
        )
    )


@router.get("/{post_id}", response_model=PostRead)
async def read_post(
    post_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PostsRead,
    include_deleted: IncludeDeletedDep = False,
) -> PostRead:
    """Read one notice. A scheduled one is its writers' until it goes up; to
    anyone else it is not there (the posts read policy)."""
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    return await _post_read(session, post, guild_context)


@router.post("/", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def create_post(
    post_in: PostCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PostsWrite,
) -> PostRead:
    """Post a notice to an initiative's board. Requires create_posts permission
    on the initiative (or guild admin); the author gets the owner grant."""
    resource_access.refuse_plugin_sharing(guild_context, post_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.post, post_in.initiative_id, current_user, guild_context
    )

    now = datetime.now(timezone.utc)
    # A schedule in the past is somebody asking for it now, which is what an
    # omitted one means too — so both take the same branch rather than one of
    # them being an error.
    scheduled = (
        post_in.scheduled_for
        if post_in.scheduled_for is not None and post_in.scheduled_for > now
        else None
    )
    post = Post(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=post_in.name.strip(),
        body=_validated_body(post_in.body),
        scheduled_for=scheduled,
        published_at=None if scheduled else now,
    )
    session.add(post)
    await session.flush()
    await metadata_service.write_on_create(session, post, post_in.properties)

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.post,
        user=current_user,
        resource_id=post.id,
        initiative_id=initiative.id,
        payload=post_in,
        grants=post_in.grants,
    )

    # What the new body points at becomes `references` edges.
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.post, post.id),
        body=post.body,
        author_id=guild_context.user_id,
    )
    await attachments_service.claim_uploads(session, post)

    if post_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.post],
            guild_id=guild_context.guild_id,
            entity_id=post.id,
            tag_ids=post_in.tag_ids,
        )

    if post_in.poll is not None:
        session.add(post_polls_service.write_poll(post, _validated_poll(post_in.poll)))
    await required_fields.refuse_missing(session, guild_context, post)

    if post.published_at is not None:
        author = await notifications_service.author_of(
            session, guild_context, current_user
        )
        await _announce(session, post, author, guild_context)

    await session.commit()
    return await read_after_write(session, post.id, current_user, guild_context)


@router.patch("/{post_id}", response_model=PostRead)
async def update_post(
    post_id: int,
    post_in: PostUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PostsWrite,
) -> PostRead:
    """Edit a notice — its headline, its body, or a schedule not yet reached.
    Requires write access.

    ``scheduled_for`` moves a pending schedule; sending it as ``null`` publishes
    the draft immediately, which is how "post it now" is expressed. Sending it
    at all on a notice that is already up is a 409: publication is not
    reversible, because the people it was announced to have already been told.

    Pinning is deliberately not here: it is a different authority, and lives on
    its own route below.
    """
    post = await resource_access.load_authorized(
        session,
        Tool.post,
        post_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    publish_now = False
    now = datetime.now(timezone.utc)
    update_data = post_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        post.name = update_data["name"].strip()
        updated = True
    body_changed = False
    if "body" in update_data and update_data["body"] is not None:
        post.body = _validated_body(update_data["body"])
        body_changed = True
        updated = True
    if "scheduled_for" in update_data:
        when = update_data["scheduled_for"]
        if post.published_at is not None:
            # Already up. "Post it now" (a null) is simply nothing left to do;
            # holding it back again is refused, because the people it was
            # announced to have already been told.
            if when is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=PostMessages.ALREADY_PUBLISHED,
                )
        elif when is not None and when > now:
            post.scheduled_for = when
            updated = True
        else:
            # Cleared, or moved to a moment that has passed: it goes up now.
            post.scheduled_for = None
            post.published_at = now
            publish_now = True
            updated = True

    if updated:
        post.updated_at = now
        session.add(post)
        if body_changed:
            await content_references.sync_for_entity(
                session,
                Endpoint(SearchEntityType.post, post.id),
                body=post.body,
                author_id=guild_context.user_id,
            )
            await attachments_service.claim_uploads(session, post)
        if publish_now:
            await post_polls_service.open_lapsed_polls(session, [post.id], now=now)
            author = await notifications_service.author_of(
                session, guild_context, current_user
            )
            await _announce(session, post, author, guild_context)
        await session.commit()

    return await read_after_write(session, post.id, current_user, guild_context)


@router.put("/{post_id}/pin", response_model=PostRead)
async def set_post_pin(
    post_id: int,
    pin_in: PostPinUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PostsWrite,
) -> PostRead:
    """Pin a notice to the top of the board, or take it back down.

    A pin puts one person's notice above everyone else's, so it asks for
    authority over the initiative — guild admin or an initiative manager —
    rather than write access on the post. Read access on the post is required
    first, then that authority.

    An optional ``expires_at`` lets a notice about a date stop shouting once
    the date passes: the pin simply stops counting and the post falls back into
    the feed by its own age. Nothing sweeps the columns afterwards — a lapsed
    pin is still the record of who pinned it and when.

    Sending ``pinned`` on a pin that is already live changes only the expiry —
    the pin keeps its original time and author. A pin that has lapsed is a new
    pin, so that one re-stamps.

    An installed plug-in manages no initiative, so it pins the notices it may
    write: its own, and the ones shared with it at write.
    """
    post = await resource_access.load_authorized(
        session,
        Tool.post,
        post_id,
        current_user,
        guild_context,
        access="read" if current_user is not None else "write",
    )
    if current_user is not None and not guild_context.is_admin:
        is_manager = await rls_service.is_initiative_manager(
            session, initiative_id=post.initiative_id
        )
        if not is_manager:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=PostMessages.PIN_MANAGER_REQUIRED,
            )

    now = datetime.now(timezone.utc)
    if pin_in.pinned:
        if pin_in.expires_at is not None and pin_in.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=PostMessages.PIN_EXPIRY_IN_PAST,
            )
        # Pinning something already pinned is a change to the expiry, not a new
        # pin: keep who pinned it and when, so putting an end date on a
        # three-day-old pin does not vault it over the pins made since.
        if not post.is_pinned_now(now):
            post.pinned_at = now
            post.pinned_by = guild_context.user_id
        post.pin_expires_at = pin_in.expires_at
    else:
        post.pinned_at = None
        post.pinned_by = None
        post.pin_expires_at = None

    post.updated_at = now
    session.add(post)
    await session.commit()
    return await read_after_write(session, post.id, current_user, guild_context)


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


@router.put("/{post_id}/reactions", response_model=PostReactionSettings)
async def set_post_reaction_settings(
    post_id: int,
    settings_in: PostReactionSettings,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostReactionSettings:
    """Turn reactions on a notice on or off.

    The counterpart to the generic comment switch, and it asks the same level:
    write access on the post, which is what putting the notice up took. There
    is no generic route for it because a post is the only thing that takes
    reactions of its own — everywhere else they hang off a comment, and that
    thread's own switch already answers.

    Turning it off keeps the reactions already there, the same way turning a
    thread off keeps its comments: the board stops showing the bar and the API
    stops serving or adding to it until the switch goes back on.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context, access="write"
    )
    post.reactions_enabled = settings_in.reactions_enabled
    post.updated_at = datetime.now(timezone.utc)
    session.add(post)
    await session.commit()
    return PostReactionSettings(reactions_enabled=post.reactions_enabled)


# ---------------------------------------------------------------------------
# Read receipts
# ---------------------------------------------------------------------------


@router.post("/read", status_code=status.HTTP_200_OK, response_model=PostReadReceipt)
async def mark_posts_read(
    body: PostReadMarks,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostReadReceipt:
    """Record that the caller has read these notices.

    A batch, because the board marks a notice read once it has been on screen
    and a page is twenty of them — one request per card would be twenty
    requests per scroll. Idempotent: sending the same page again inserts
    nothing and answers the same way.

    A receipt is recorded for the notices among these the caller can see, and
    the service applies the board's own sharing and publication conditions to
    decide which those are.
    """
    marked = await posts_service.mark_read(
        session,
        body.post_ids,
        user_id=current_user.id,
    )
    await session.commit()
    return PostReadReceipt(marked=marked)


@router.delete("/{post_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_post_unread(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Put one notice back to unread for the caller.

    Read access, not write: this is the reader's own state, and it says nothing
    about the notice. Silent when there was no receipt — asking for a state a
    thing is already in is not an error.
    """
    await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    await posts_service.mark_unread(session, post_id, user_id=current_user.id)
    await session.commit()


@router.get("/{post_id}/reads", response_model=PostReaders)
async def list_post_readers(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostReaders:
    """Who has read this notice, and who it is still waiting on.

    Offered to anyone who can read the post rather than only its author: a
    board is where things are said out loud, and whether a notice landed is the
    point of saying it there. What it discloses is bounded by the sharing —
    the roster is the people the notice went to, who already know of each other
    through the initiative they share.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    receipts, waiting_ids = await posts_service.list_readers(session, post)
    waiting = await posts_service.load_member_profiles(session, waiting_ids)
    return PostReaders(
        read=[
            post_reader(receipt.reader, read_at=receipt.read_at)
            for receipt in receipts
            if receipt.reader is not None
        ],
        unread=[post_reader(profile) for profile in waiting],
    )


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------


@router.put("/{post_id}/poll", response_model=PostRead)
async def set_post_poll(
    post_id: int,
    poll_in: PollWrite,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Give a notice its question, or rewrite the one it has.

    Write access, the same as the body: a poll is part of what the notice says.
    One route rather than a create and an update, because a poll is written and
    read as a whole — "the third choice" only means anything beside the other
    two.

    Three things are refused once somebody has answered, and each protects a
    vote already cast rather than the author's convenience:

    * **Changing the choices.** A ballot cast for "Tuesday" must not silently
      become a ballot for whatever took third place. The question, the close
      time and the switches below stay editable.
    * **Switching anonymity off.** People answered on the understanding that
      their names were not attached, and that cannot be revoked afterwards.
    * **Switching multiple choice off.** Somebody who ticked three answers
      would otherwise be left holding three ballots on a poll that takes one,
      and the roster would list one voter under several choices.

    Both switches can always be turned *on* — each only ever tightens what
    happens next, and neither rewrites an answer already given.

    The poll's row is taken before any of that is asked and held until the edit
    commits, so "has anybody answered?" and the write that acts on the answer
    are one step.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context, access="write"
    )
    data = _validated_poll(poll_in)
    existing = post.poll
    if existing is not None:
        await post_polls_service.lock_poll(
            session, existing, guild_id=guild_context.guild_id
        )
        if await post_polls_service.has_votes(session, existing):
            if not post_polls_service.options_match(existing, data):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=PostMessages.POLL_HAS_VOTES,
                )
            if existing.is_anonymous and not data.is_anonymous:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=PostMessages.POLL_ANONYMITY_LOCKED,
                )
            if existing.allows_multiple and not data.allows_multiple:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=PostMessages.POLL_MULTIPLE_LOCKED,
                )
    session.add(post_polls_service.write_poll(post, data, poll=existing))
    post.updated_at = datetime.now(timezone.utc)
    session.add(post)
    await session.commit()
    return await read_after_write(session, post_id, current_user, guild_context)


@router.delete("/{post_id}/poll", response_model=PostRead)
async def delete_post_poll(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Take the question off a notice.

    Write access, and it takes the answers with it — which is why it is a
    deliberate act on its own route rather than a side effect of an edit. The
    notice itself stays; only the question goes.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context, access="write"
    )
    poll = _poll_of(post)
    await session.delete(poll)
    post.poll = None
    post.updated_at = datetime.now(timezone.utc)
    session.add(post)
    await session.commit()
    return await read_after_write(session, post_id, current_user, guild_context)


@router.put("/{post_id}/poll/vote", response_model=PostRead)
async def vote_on_post_poll(
    post_id: int,
    vote_in: PollVoteWrite,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Answer a notice's question.

    Read access — answering is a reader's gesture, like reacting, not an edit
    of the notice. A PUT rather than a POST because a ballot is replaced rather
    than added to: sending it again is changing your mind, and sending it twice
    leaves the same answer.

    Answers the whole post, so a card that has just voted re-renders from one
    response with the new tallies in it.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    if not post.is_published:
        # A draft reaches only the people who could edit it, and a question
        # nobody has been asked yet has no answers to collect.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PostMessages.POLL_NOT_PUBLISHED,
        )
    poll = _poll_of(post)
    # Takes the poll's row and asks whether it still takes votes in one
    # statement, against the wall clock at that moment. The row is held until
    # this ballot commits, so one voter's ballots are written one after another
    # and each is measured by the deadline in force as it lands.
    if not await post_polls_service.lock_open_poll(
        session, poll, guild_id=guild_context.guild_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PostMessages.POLL_CLOSED,
        )
    if not poll.allows_multiple and len(vote_in.option_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.POLL_SINGLE_CHOICE,
        )
    known = {option.id for option in poll.options or []}
    if not set(vote_in.option_ids) <= known:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PostMessages.POLL_OPTION_UNKNOWN,
        )
    await post_polls_service.cast_vote(
        session, poll, user_id=current_user.id, option_ids=vote_in.option_ids
    )
    await session.commit()
    return await read_after_write(session, post_id, current_user, guild_context)


@router.delete("/{post_id}/poll/vote", response_model=PostRead)
async def retract_post_poll_vote(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PostRead:
    """Take back this reader's answer.

    Allowed while the poll is open, for the same reason changing it is: until
    voting stops, an answer is what somebody currently thinks. Silent when
    there was none.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    poll = _poll_of(post)
    if not await post_polls_service.lock_open_poll(
        session, poll, guild_id=guild_context.guild_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=PostMessages.POLL_CLOSED,
        )
    await post_polls_service.retract_vote(session, poll, user_id=current_user.id)
    await session.commit()
    return await read_after_write(session, post_id, current_user, guild_context)


@router.get("/{post_id}/poll/voters", response_model=PollVoters)
async def list_post_poll_voters(
    post_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> PollVoters:
    """Who chose what, and who has not answered.

    Offered to anyone who can read the notice, like its read roster: the people
    named are the people it went to, who already know of each other through the
    initiative they share.

    Refused in the two cases where the poll itself says not to — an anonymous
    poll, which has no roster by design, and one whose results are still
    withheld from this reader.
    """
    post = await resource_access.load_authorized(
        session, Tool.post, post_id, current_user, guild_context
    )
    poll = _poll_of(post)
    if poll.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PostMessages.POLL_IS_ANONYMOUS,
        )
    await post_polls_service.annotate_poll_state(
        session, [post], user_id=current_user.id
    )
    if not serialize_poll(poll).results_visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PostMessages.POLL_RESULTS_HIDDEN,
        )
    by_option, waiting_ids = await post_polls_service.list_voters(session, post, poll)
    waiting = await posts_service.load_member_profiles(session, waiting_ids)
    return PollVoters(
        options=[
            PollOptionVoters(
                option_id=option.id,
                voters=[
                    poll_voter(profile) for profile in by_option.get(option.id, [])
                ],
            )
            for option in sorted(poll.options or [], key=lambda o: (o.position, o.id))
        ],
        not_voted=[poll_voter(profile) for profile in waiting],
    )
