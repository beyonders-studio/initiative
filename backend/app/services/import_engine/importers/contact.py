"""``initiative-contact`` importer: one contact, its tags and its properties.

A contact holds nothing else, so applying one is creating a single row. Its
details are held by the envelope to the rules a create holds them to. Names
may repeat — two people can share one — so an imported contact keeps the
name it carries.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.contact import DETAILS, Contact
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import ContactEnvelope
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)


class ContactImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.contact)
    permission = PermissionKey(Tool.contact.create_permission)

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(ContactEnvelope, envelope)

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
        env: ContactEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model

        contact = Contact(
            initiative_id=target_initiative.id,
            created_by=importer.id,
            **env.model_dump(include={"name", "is_organization", *DETAILS}),
        )
        session.add(contact)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.contact,
            entity_id=contact.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(contact, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(contact, env.properties)
        return EnvelopeImportResult(
            entity_id=contact.id,
            entity_title=contact.name,
            created={
                Tool.contact.plural: 1,
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=await props.settle(contact),
        )
