"""The single resource-grant (sharing) schema for every tool.

Everything is a row in ``resource_grants``, so there is **one** shape:
``ResourceGrantSchema``. A resource's sharing state is just a list of them — the
identical shape both reports the grants (``grants`` on the read models) and
replaces them (the ``PUT /{id}/grants`` body). Lives in its own module so every
tool's schema can import it without a cycle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.identity_boundary import PersonId
from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.base import SanitizedBaseModel

# Upper bound on how many resources one bulk grant request may touch. Each item is
# a load + authorize + rewrite + commit, so an unbounded list makes a slow
# request; a multi-select bulk-edit UI never needs more than this in one call.
MAX_BULK_GRANT_ITEMS = 200


class ResourceGrantSchema(SanitizedBaseModel):
    """One ``resource_grants`` row — exactly the columns that define a grant: a
    ``level`` for a user (``user_id``), an initiative role (``role_id``), all
    initiative members (``all_initiative_members``), or an installed plug-in
    (``plugin_install_id``). Exactly one grantee is set.

    The identical shape both reports a resource's grants (``grants`` is a list of
    these) and replaces them (the ``PUT /{id}/grants`` body) — no field is
    read-only or write-only. The server always preserves the resource's owner
    grant. Role display names are resolved client-side from the initiative's roles
    by ``role_id``.

    A **plug-in install** grantee is reported here and not taken from here: kept by
    the server whatever this list says. What a plug-in may reach is the seat's to
    decide, not a resource owner's sharing panel."""

    # from_attributes so a read model can validate straight off the ORM
    # ResourceGrant row (e.g. ProjectRead.model_validate(project) reading
    # project.grants).
    model_config = ConfigDict(from_attributes=True)

    level: ResourceAccessLevel
    user_id: PersonId | None = None
    role_id: int | None = None
    all_initiative_members: bool = False
    #: The installed plug-in this grant is made to. Reported, never taken.
    plugin_install_id: int | None = None

    @model_validator(mode="after")
    def exactly_one_grantee(self) -> ResourceGrantSchema:
        count = (
            (self.user_id is not None)
            + (self.role_id is not None)
            + self.all_initiative_members
            + (self.plugin_install_id is not None)
        )
        if count != 1:
            raise ValueError(
                "Exactly one of user_id, role_id, all_initiative_members "
                "or plugin_install_id must be set"
            )
        return self


def initiative_readable() -> list[ResourceGrantSchema]:
    """The sharing a new tool starts with unless its create says otherwise:
    every member of its initiative may read it."""
    return [ResourceGrantSchema(all_initiative_members=True, level="read")]


class ResourceGrantBulkItem(SanitizedBaseModel):
    """One tool's full target sharing state in a bulk request — the same ``grants``
    body the per-resource ``PUT /{id}/grants`` takes, tagged with which tool it
    applies to (the app-wide ``Tool`` enum)."""

    resource_type: Tool
    resource_id: int
    grants: list[ResourceGrantSchema]


class ResourceGrantBulkRequest(SanitizedBaseModel):
    """Replace sharing on many resources (possibly of different types) in one call.
    Capped at ``MAX_BULK_GRANT_ITEMS`` items (422 otherwise)."""

    items: list[ResourceGrantBulkItem] = Field(
        min_length=1, max_length=MAX_BULK_GRANT_ITEMS
    )


class ResourceGrantBulkItemResult(SanitizedBaseModel):
    """Per-item outcome — bulk is best-effort: a resource the caller can't manage
    (``forbidden``) or that doesn't exist (``not_found``) is skipped without
    blocking the rest."""

    resource_type: Tool
    resource_id: int
    status: Literal["ok", "forbidden", "not_found"]
    detail: str | None = None


class ResourceGrantBulkResponse(SanitizedBaseModel):
    results: list[ResourceGrantBulkItemResult]
