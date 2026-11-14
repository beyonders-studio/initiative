"""``initiative-project`` importer — a thin adapter over
``project_import.import_project``, which intake setup also calls directly."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.backup_export import ManifestPerson
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine.common import handle_key
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    parse_envelope,
)


class ProjectImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.project)
    permission = PermissionKey.create_projects

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(ProjectExportEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: ProjectExportEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        # A comment is a row like any other, so it counts against the
        # ceiling: a project with ten tasks and four thousand comments on
        # them is a large import however few tasks it names.
        return (
            len(envelope.tasks) + sum(len(task.comments) for task in envelope.tasks) + 1
        )

    def people(self, validated: BaseModel) -> list[ManifestPerson]:
        """Everybody this project names, most-quoted first.

        The same inventory a backup's manifest carries, taken from one
        envelope: a handle, the name it went by, and how many comments hang
        on getting that one row right. Four kinds of mention put somebody on
        it, because all four go through the answer the wizard records:

        * a comment's author, whose words land under whoever the handle is
          mapped to;
        * an assignee, whose task lands on whoever the handle is mapped to —
          still only if that account is in the target initiative (see
          ``people.initiative_member_id``);
        * a user-type property value — a Reporter, a Reviewer — placed by
          the same rule as an assignee;
        * an ``@`` mention in a description or a comment, which links to
          whoever the handle is mapped to.

        An assignee who wrote nothing is still a question worth asking. Left
        off, a handle nobody here answers to by name was applied without the
        step and reported afterwards as unmatched, with no way to say who it
        was.

        A handle the envelope spelled two ways is one person: it is keyed
        the way it is matched, and the first spelling seen is the one shown.
        """
        envelope: ProjectExportEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        seen: dict[str, ManifestPerson] = {}

        def note(handle: str | None, name: str | None, comments: int) -> None:
            handle = (handle or "").strip()
            if not handle:
                return
            key = handle_key(handle)
            person = seen.get(key)
            if person is None:
                seen[key] = ManifestPerson(
                    handle=handle, name=name, comment_count=comments
                )
                return
            person.comment_count += comments
            # A name only where one was given: the first mention of somebody
            # may be the one that carried no display name.
            if person.name is None:
                person.name = name

        for task in envelope.tasks:
            for comment in task.comments:
                note(comment.author_handle, comment.author_name, 1)
            for handle in task.assignee_handles:
                note(handle, None, 0)
        # Mentions and user-type property values, read as every envelope's are.
        for person in super().people(validated):
            note(person.handle, None, 0)
        return sorted(seen.values(), key=lambda p: (-p.comment_count, p.handle.lower()))

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        from app.services.tenant.project_import import import_project

        return await import_project(
            session,
            envelope=envelope,
            target_initiative=target_initiative,
            importer=importer,
            context=context,
        )
