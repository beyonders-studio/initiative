"""What erasing an account does to every guild-schema row that named that person.

Fourteen of those columns used to declare a delete rule — nine ``ON DELETE
CASCADE``, five ``ON DELETE SET NULL`` — on a key no guild schema has ever
held. Provisioning copies intra-schema keys only, and ``20260922_0349`` dropped
the ones ``guild_template`` alone still carried, so the rules described a
Postgres that would clear the column or take the row, and no Postgres ever did.
``app.models.tenant.cross_schema_refs_test`` now holds the line at declaring
one; this is the other half, and the half that is load-bearing: an account with
a row in each of those tables, erased, and an assertion per table about
what is actually left.

Three outcomes appear below, and the distinction is the point:

* **The row goes** — per-person state and anything held in custody for them.
  ``app.services.platform.users`` deletes it, in every guild schema.
* **The row stays, un-attributed** — a record of something that happened,
  whose subject can be dropped without losing the event.
* **The row stays, still naming them** — authorship. ``created_by`` is a weak
  reference on purpose: it outlives the account so an old thread keeps telling
  one departed author from another, rather than merging them into a shared
  placeholder (see ``CreatedByMixin``). A block tombstone stays for a
  neighbouring reason — it outlives the membership it was placed on.

``webhook_subscriptions.created_by`` used to be none of those — it named the
account a delivery was read as. It is ordinary authorship now, so it belongs to
the third group with the rest.

Both erasure paths run the same per-guild erasure and differ only in what
happens to the shared ``users`` row: ``soft_delete_user`` is what the product
runs (the deletion request and the retention purge; the row stays, emptied), and
``hard_delete_user`` is the operator's removal of the row itself.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import RelationshipType
from app.models.platform.guild import CommunityRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.batched_notice import BatchedNotice, BatchedNoticeKind
from app.models.tenant.comment import Comment
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.initiative import InitiativeJoinRequest
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.plugin_member_consent import PluginMemberConsent
from app.models.tenant.reaction import Reaction
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.view_preference import ViewPreference
from app.models.tenant.webhook_ref import WebhookRef
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.platform import users as user_service
from app.services.tenant import relationships, webhook_refs
from app.services.tenant.mention_parser import ANONYMIZED_MENTION_NAME
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
    create_comment,
    create_file,
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_initiative,
    create_initiative_member,
    create_project,
    create_reaction,
    create_task,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild


def _service_definition() -> dict:
    """A service plug-in declaring one connection, so a credential row has a home."""
    return {
        "plugin_kind": "service",
        "service": {"public_id": "tests.erasure", "protocol": 1},
        "features": [],
        "default_name": "Erasure",
        "connections": [
            {
                "id": "admin",
                "scope": "static",
                "label": {"en": "Admin API"},
                "fields": [{"key": "token", "type": "string", "label": {"en": "T"}}],
            }
        ],
    }


async def _seed(session: AsyncSession) -> SimpleNamespace:
    """One member, and one row naming them in each of the tables."""
    keeper = await create_user(session, email=f"keeper-{secrets.token_hex(4)}@e.test")
    victim = await create_user(session, email=f"leaver-{secrets.token_hex(4)}@e.test")
    guild = await create_guild(session, creator=keeper)
    await create_guild_membership(
        session, user=victim, guild=guild, role=CommunityRole.member
    )
    initiative = await create_initiative(session, guild, keeper)
    await create_initiative_member(session, initiative=initiative, user=victim)
    project = await create_project(session, initiative, keeper)
    task = await create_task(session, project)
    file = await create_file(session, initiative, keeper)
    calendar = await create_calendar(session, initiative, keeper)
    event = await create_calendar_event(session, calendar, keeper)
    plugin = await create_guild_plugin(
        session, guild, keeper, definition=_service_definition()
    )

    # Authorship: a comment they wrote, and an emoji they put on it.
    comment = await create_comment(session, victim, file=file)
    reaction = await create_reaction(session, victim, comment=comment)

    now = datetime.now(UTC)
    await route_session_to_guild(session, guild.id)
    rows = {
        # A receipt that a reminder for this event reached this person.
        "dispatch": EventReminderDispatch(
            event_id=event.id,
            user_id=victim.id,
            event_start_at=now,
            sent_at=now,
        ),
        # A vendor credential they connected, and one they blocked for somebody.
        "connection": GuildPluginUserConnection(
            plugin_id=plugin.id,
            connection_id="admin",
            user_id=victim.id,
            connection_ref=secrets.token_hex(8),
        ),
        "blocked_connection": GuildPluginUserConnection(
            plugin_id=plugin.id,
            connection_id="admin",
            user_id=keeper.id,
            connection_ref=secrets.token_hex(8),
            blocked_at=now,
            blocked_by_id=victim.id,
        ),
        # Consent for a plug-in to act as them, and one they withdrew for
        # somebody else.
        "consent": PluginMemberConsent(
            install_id=plugin.id,
            user_id=victim.id,
            label="Act as me",
            requested_access="read",
            granted_access="read",
            granted_at=now,
        ),
        "revoked_consent": PluginMemberConsent(
            install_id=plugin.id,
            user_id=keeper.id,
            label="Act as me",
            requested_access="read",
            granted_access="read",
            granted_at=now,
            revoked_at=now,
            revoked_by_id=victim.id,
        ),
        # A request they made, and one they ruled on.
        "own_request": InitiativeJoinRequest(
            initiative_id=initiative.id,
            user_id=victim.id,
            status="approved",
            resolved_at=now,
            resolved_by=keeper.id,
        ),
        "ruled_request": InitiativeJoinRequest(
            initiative_id=initiative.id,
            user_id=keeper.id,
            status="denied",
            resolved_at=now,
            resolved_by=victim.id,
        ),
        # Queued notifications naming them as the one who acted.
        "reaction_line": BatchedNotice(
            user_id=keeper.id,
            kind=BatchedNoticeKind.reaction,
            actor_id=victim.id,
            actor_name="Leaver",
            target_type="comment",
            target_id=comment.id,
            target_path="/x",
            title="a comment",
            reaction_id=reaction.id,
            emoji="\N{THUMBS UP SIGN}",
        ),
        "assignment_line": BatchedNotice(
            user_id=keeper.id,
            kind=BatchedNoticeKind.task_assignment,
            actor_id=victim.id,
            actor_name="Leaver",
            target_type="task",
            target_id=task.id,
            target_path=f"/go/task/{task.id}",
            title="A task",
            project_id=project.id,
            project_name="A project",
        ),
        # A live outbound integration they registered.
        "webhook": WebhookSubscription(
            initiative_id=initiative.id,
            created_by=victim.id,
            created_by_kind=ActorKind.member,
            target_url="https://example.test/hook",
            hmac_secret=secrets.token_hex(16),
            event_types=["task.created"],
            created_at=now,
            updated_at=now,
        ),
    }
    for row in rows.values():
        session.add(row)
    await session.commit()
    for row in rows.values():
        await session.refresh(row)

    seeded = SimpleNamespace(
        guild_id=guild.id,
        victim_id=victim.id,
        keeper_id=keeper.id,
        task_id=task.id,
        comment_id=comment.id,
        reaction_id=reaction.id,
        **{name: row.id for name, row in rows.items()},
    )
    session.expunge_all()
    return seeded


async def _reread(session: AsyncSession, guild_id: int, model, row_id: int):
    """One row from the guild's schema, or ``None`` if erasure took it."""
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return (await session.exec(select(model).where(model.id == row_id))).one_or_none()


@pytest.mark.parametrize(
    "erase",
    [user_service.soft_delete_user, user_service.hard_delete_user],
    ids=["soft", "hard"],
)
async def test_erasure_leaves_each_row_as_it_should(
    session: AsyncSession, role_session, erase
):
    s = await _seed(session)
    await route_session_to_guild(session, s.guild_id)
    for person in (s.victim_id, s.keeper_id):
        session.add(
            PersonalItem(
                user_id=person,
                entity_type="project",
                entity_id=1,
                bookmarked_at=datetime.now(UTC),
            )
        )
        session.add(
            ViewPreference(user_id=person, scope_key="view:project:1", value={})
        )
    task = relationships.Endpoint("task", s.task_id)
    victim = relationships.Endpoint("user", s.victim_id)
    keeper = relationships.Endpoint("user", s.keeper_id)
    for source, relationship_type, target in (
        (task, RelationshipType.depends_on, victim),
        (victim, RelationshipType.part_of, task),
        (task, RelationshipType.related_to, keeper),
    ):
        await relationships.create(
            session, source=source, relationship_type=relationship_type, target=target
        )
    await session.commit()
    await webhook_refs.name_for_subscriber(
        guild_id=s.guild_id,
        plugin=None,
        subscription_id=s.webhook,
        actor_ids=(s.victim_id, s.keeper_id),
    )

    await erase(await role_session("app_admin"), s.victim_id)
    session.expunge_all()
    await route_session_to_guild(session, s.guild_id)

    # --- the row goes ---
    # Opens, bookmarks, subscriptions, orders and list views are one person's
    # own: theirs go, and someone else's stay.
    assert (await session.exec(select(PersonalItem.user_id))).all() == [s.keeper_id]
    assert (await session.exec(select(ViewPreference.user_id))).all() == [s.keeper_id]
    # Every per-person DAC grant in the schema, in one delete.
    assert (
        await session.exec(
            select(ResourceGrant).where(ResourceGrant.user_id == s.victim_id)
        )
    ).all() == []
    # A subscription's receiver holds a name for each person it was told
    # about. Theirs goes; the community's and somebody else's stay.
    left = (
        await session.exec(select(WebhookRef.entity_type, WebhookRef.entity_id))
    ).all()
    assert sorted(left) == [("guild", s.guild_id), ("user", s.keeper_id)]
    # Every link with them on an end, whichever end; one to somebody else stays.
    left = (
        await session.exec(
            select(EntityRelationship.source_type, EntityRelationship.target_id)
        )
    ).all()
    assert left == [("task", s.keeper_id)]
    # Losing the account ends the vendor access it opened and what a plug-in
    # could do as them.
    assert (
        await _reread(session, s.guild_id, GuildPluginUserConnection, s.connection)
        is None
    )
    assert await _reread(session, s.guild_id, PluginMemberConsent, s.consent) is None
    # The reminder ledger is kept only to not send the same reminder twice: it
    # can never match again, and it names somebody who is gone.
    assert await _reread(session, s.guild_id, EventReminderDispatch, s.dispatch) is None

    # --- the row stays, un-attributed ---
    # Somebody else's queued lines survive, a reaction's and an assignment's
    # alike; the id and the name of the one who acted do not.
    for line in (s.reaction_line, s.assignment_line):
        row = await _reread(session, s.guild_id, BatchedNotice, line)
        assert row is not None
        assert row.actor_id is None
        assert row.actor_name == ANONYMIZED_MENTION_NAME

    # --- the row stays, still naming them ---
    # Authorship is a weak reference: the thread still tells them apart.
    for model, row_id in ((Comment, s.comment_id), (Reaction, s.reaction_id)):
        row = await _reread(session, s.guild_id, model, row_id)
        assert row is not None
        assert row.created_by == s.victim_id
    # A block outlives the membership it was placed on, and the account too; a
    # consent withdrawal they performed on somebody else's reads the same.
    row = await _reread(
        session, s.guild_id, GuildPluginUserConnection, s.blocked_connection
    )
    assert row is not None
    assert row.blocked_by_id == s.victim_id
    row = await _reread(session, s.guild_id, PluginMemberConsent, s.revoked_consent)
    assert row is not None
    assert row.revoked_by_id == s.victim_id
    # A request carries a message its author wrote, and a ruling names the
    # manager who made it. Erasure keeps both, the way it keeps a comment.
    made = await _reread(session, s.guild_id, InitiativeJoinRequest, s.own_request)
    assert made is not None
    assert made.user_id == s.victim_id
    ruled = await _reread(session, s.guild_id, InitiativeJoinRequest, s.ruled_request)
    assert ruled is not None
    assert ruled.resolved_by == s.victim_id
    # A subscription is the community's integration configuration, and its
    # reach is the scope it names rather than anyone's standing — so erasing
    # the person who registered it is not a decision about it.
    row = await _reread(session, s.guild_id, WebhookSubscription, s.webhook)
    assert row is not None
    assert row.active is True
    assert row.created_by == s.victim_id
