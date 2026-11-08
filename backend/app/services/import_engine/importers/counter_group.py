"""``initiative-counter-group`` importer: the group with its tags, and its
counters with configuration and current values."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant._mixins import ActorKind
from app.models.tenant.counter import Counter, CounterGroup, CounterViewMode
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import CounterGroupEnvelope
from app.services.import_engine.common import unique_name_in_initiative
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)


class CounterGroupImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.counter_group)
    permission = PermissionKey.create_counter_groups

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(CounterGroupEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: CounterGroupEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.counters) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: CounterGroupEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model

        group = CounterGroup(
            name=await unique_name_in_initiative(
                session, CounterGroup, target_initiative.id, env.name
            ),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
            created_by_kind=ActorKind.member,
        )
        session.add(group)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.counter_group,
            entity_id=group.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(group, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(group, env.properties)

        for c in env.counters:
            try:
                view_mode = CounterViewMode(c.view_mode)
            except ValueError:
                view_mode = CounterViewMode.number
            counter = Counter(
                counter_group_id=group.id,
                name=c.name,
                color=c.color,
                count=_dec(c.count),
                min=_dec(c.min),
                max=_dec(c.max),
                step=_dec(c.step),
                initial_count=_dec(c.initial_count),
                view_mode=view_mode,
                position=_dec(c.position),
            )
            session.add(counter)
            await session.flush()
            if context is not None:
                context.links.register(
                    c.external_ref, SearchEntityType.counter, counter.id
                )
            await props.attach(counter, c.properties)

        return EnvelopeImportResult(
            entity_id=group.id,
            entity_title=group.name,
            created={
                Tool.counter_group.plural: 1,
                "counters": len(env.counters),
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=await props.settle(group),
        )


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    # Through str so 0.1 stays 0.1, not the float's binary expansion.
    return Decimal(str(value))
