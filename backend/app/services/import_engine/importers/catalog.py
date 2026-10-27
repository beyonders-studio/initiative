"""``initiative-catalog`` importer: the catalog row, its pictures, and the
tags on both.

A picture is a row plus a blob, and only the row is in the envelope. The bytes
travel as an asset in the backup zip and are restored under their original
storage key before entries apply, so an item's ``storage_key`` resolves to a
blob that is already there. A key that resolves to nothing is **skipped and
counted**, not written: a catalog row pointing at bytes that never arrived
would be a broken tile that no one can fix.

That is why a catalog envelope on its own — outside a backup — imports as an
empty catalog and says so. Nothing is lost that was ever there.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.catalog import Catalog, CatalogItem
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import CatalogEnvelope
from app.services.import_engine.common import unique_name_in_initiative
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.tenant import file_versions


class CatalogImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.catalog)
    permission = PermissionKey.create_catalogs

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(CatalogEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: CatalogEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.items) + 1

    def archive_assets(
        self, envelope: dict[str, Any]
    ) -> list[tuple[dict[str, Any], str]]:
        """The pictures an exported catalog's zip carries beside it, as the
        envelope names them: each one's ``storage_key`` is its file under
        ``assets/``."""
        items = envelope.get("items")
        if not isinstance(items, list):
            return []
        return [(item, "picture") for item in items if isinstance(item, dict)]

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: CatalogEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = routed_guild_id(session)
        warnings: list[str] = []

        catalog = Catalog(
            name=await unique_name_in_initiative(
                session, Catalog, target_initiative.id, env.name
            ),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(catalog)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.catalog,
            entity_id=catalog.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(catalog, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(catalog, env.properties)

        created = 0
        missing = 0
        cover_id: int | None = None
        for image_env in env.items:
            key = (image_env.storage_key or "").strip()
            # A key with a path in it is not a key. The backup importer holds
            # assets to the same rule when it restores them.
            if not key or "/" in key or "\\" in key or key in (".", ".."):
                missing += 1
                continue
            # Stored here, and a picture a catalog shows, by its bytes.
            content_type = await file_versions.stored_file_type(
                CatalogItem, guild_id, key
            )
            if content_type is None:
                missing += 1
                continue
            row = CatalogItem(
                catalog_id=catalog.id,
                title=image_env.title,
                description=image_env.description,
                **(
                    {"occurred_on": image_env.occurred_on}
                    if image_env.occurred_on is not None
                    else {}
                ),
                created_by=importer.id,
            )
            session.add(row)
            await session.flush()
            await file_versions.add_version(
                session,
                row,
                created_by=importer.id,
                file_url=f"/uploads/{guild_id}/{key}",
                file_content_type=content_type,
                file_size=image_env.size_bytes,
                original_filename=image_env.original_filename,
                width=image_env.width,
                height=image_env.height,
            )
            if context is not None:
                context.links.register(
                    image_env.external_ref, SearchEntityType.catalog_item, row.id
                )
            created += 1
            if env.cover and key == env.cover:
                cover_id = row.id
            await tags.attach(row, image_env.tags)
            await props.attach(row, image_env.properties)

        if cover_id is not None:
            catalog.cover_item_id = cover_id
            session.add(catalog)
        if missing:
            # The list a catalog draws is its pictures, so a missing one is
            # worth saying out loud rather than leaving somebody to count.
            warnings.append(f"missing_image_files:{missing}")

        return EnvelopeImportResult(
            entity_id=catalog.id,
            entity_title=catalog.name,
            created={
                Tool.catalog.plural: 1,
                "items": created,
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            failed={"items": missing} if missing else {},
            unmatched_handles=await props.settle(catalog),
            warnings=warnings,
        )
