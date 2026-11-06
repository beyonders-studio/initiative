"""Contact source adapter: the importable backup envelope (json).

A contact is its name, whether it is an organization, and how to reach it, so
the envelope carries those whole, with its tags and properties. Its sharing
and its links are the community's and stay behind, as every tool's do.

Access rule: READ on the contact (exporting is a formatted read), enforced by
the ``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from typing import Any

from app.core.tools import Tool, tool_envelope_type
from app.models.tenant.contact import DETAILS, Contact
from app.schemas.tenant.tag import annotated_tags
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties


class ContactAdapter(ToolExportAdapter):
    tool = Tool.contact

    def item(self, contact: Contact, ctx: BuildContext, /) -> RenderItem:
        return RenderItem(
            key=envelope_key(Tool.contact, contact.name, ctx.date),
            data=_envelope(contact),
        )


def _envelope(contact: Contact) -> dict[str, Any]:
    return {
        "type": tool_envelope_type(Tool.contact),
        "schema_version": 1,
        "name": contact.name,
        "is_organization": contact.is_organization,
        **{field: list(getattr(contact, field)) for field in DETAILS},
        "tags": sorted(tag.name for tag in annotated_tags(contact)),
        "properties": exported_properties(contact),
    }
