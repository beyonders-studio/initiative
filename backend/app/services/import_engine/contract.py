"""Import-engine contract: the per-type importer protocol and result shapes.

The engine mirrors the export engine structurally (registry → bound check →
inline-or-job), with one inversion stated once here: **imports are writes,
always** — there is no inline path for read-only actors, and every importer's
``apply`` inserts rows as the importing user.

``apply`` is flush-only: the CALLER owns the transaction (the endpoint
commits an inline apply; the worker commits a job apply; the future backup
orchestrator commits per chunk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.schemas.base import SanitizedBaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.schemas.tenant.backup_export import ManifestPerson
    from app.services.import_engine.context import ImportContext


class ImportEngineError(CodedError):
    """Engine-level failure with a machine-readable code (``messages.py``
    constant). The API answers it with its status; the worker records the
    code on the failed job row. (Named to avoid the ``ImportError`` builtin.)
    """


class EnvelopeImportResult(SanitizedBaseModel):
    """One envelope's apply outcome — JSON-serializable because it is
    persisted verbatim into ``data_jobs.result`` and rendered by the UI."""

    entity_id: int | None = None
    entity_title: str = ""
    # Row counts by noun, e.g. {"tasks": 12, "tags": 3, "events": 4}.
    created: dict[str, int] = {}
    # Existing rows reused instead of created (tags, property definitions).
    matched: dict[str, int] = {}
    # Rows that failed inside a partial-success apply (per-event savepoints),
    # by noun — structured so the UI never parses warning strings for counts.
    failed: dict[str, int] = {}
    # Property definitions that collided by name and were created renamed
    # (names when known, count always).
    renamed_properties: list[str] = []
    renamed_property_count: int = 0
    # Edges the deferred pass wrote for this envelope, and the ones whose far
    # end was never imported. Zero on every importer that reads no links.
    links_created: int = 0
    links_unresolved: int = 0
    # Emails in the envelope that matched no member of the target initiative.
    unmatched_handles: list[str] = []
    warnings: list[str] = []


@dataclass
class InlineImport:
    """A small envelope applied in-request — no job row persisted (the
    mirror of the export engine's ``InlineExport``)."""

    result: EnvelopeImportResult


class EnvelopeImporter(Protocol):
    """One importer per envelope ``type`` — the registry in
    ``importers/__init__.py`` maps the discriminator to an instance."""

    # The envelope ``type`` value this importer consumes.
    envelope_type: str
    # The initiative-role permission gating the import (creating content).
    permission: str

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        """Pydantic-parse + schema_version-gate the raw envelope. Raises
        ImportEngineError(IMPORT_INVALID_ENVELOPE /
        IMPORT_SCHEMA_VERSION_UNSUPPORTED)."""
        ...

    def count(self, validated: BaseModel) -> int:
        """Cheap in-memory row proxy for the inline-vs-job split and the
        hard ceiling (len(tasks), len(items), … — 1 for a lone file)."""
        ...

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        """Everybody this envelope quotes, most-quoted first.

        The same inventory a backup's manifest carries, read from one
        envelope instead — it is what the wizard's people step asks about,
        and what decides whether a lone envelope needs a confirm screen at
        all (``engine.start_envelope_import``).

        Most importers return nothing, and that is not a stub: an envelope
        that names no people has nobody to ask about. Only the project
        envelope carries comment authors today.
        """
        ...

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: "ImportContext | None" = None,
    ) -> EnvelopeImportResult:
        """Insert the envelope's rows (importer becomes owner, owner grant
        synthesized). Flush-only — the caller commits.

        ``context`` is what the job knows and the envelope does not
        (``import_engine.context``): the link collector, where an importer
        registers what it created under the refs its envelope gave and
        records the links it read — never resolving any, because the far end
        is usually in another entry — and the people map, which says who the
        handles in it turned out to be. Every importer accepts it; most do
        nothing with it.
        """
        ...
