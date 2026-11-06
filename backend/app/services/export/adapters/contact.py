"""Contact source adapter: the importable backup envelope (json), and a
spreadsheet of the selection (csv).

A contact is its name, whether it is an organization, and how to reach it, so
the envelope carries those whole, with its tags and properties. Its sharing
and its links are the community's and stay behind, as every tool's do.

The spreadsheet is one row per contact, in the columns the CSV import reads
back (``import_engine.contacts_csv``), so an export comes back in unchanged:
each value of a field and its label are a pair of columns, as many pairs as
the contact with the most of them needs, then the organization a person is
part of, the tags, and one column per initiative property the contacts hold.

Access rule: READ on the contact (exporting is a formatted read), enforced by
the ``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.tenant.contact import DETAILS, Contact
from app.models.tenant.metadata import MetadataType
from app.schemas.tenant.tag import annotated_tags
from app.services.export import values
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.export.i18n import et, export_locale
from app.services.export.property_values import (
    exported_properties,
    portable_summaries,
    property_export_dict,
)
from app.services.tenant import contacts as contacts_service


class ContactAdapter(ToolExportAdapter):
    tool = Tool.contact
    formats = ("json", "csv")

    def item(self, contact: Contact, ctx: BuildContext, /) -> RenderItem:
        return RenderItem(
            key=envelope_key(Tool.contact, contact.name, ctx.date),
            data=_envelope(contact),
        )

    async def prepare(
        self, session: AsyncSession, contacts: list[Contact], ctx: BuildContext, /
    ) -> Any:
        """For the spreadsheet, the organization each person is part of."""
        if ctx.format != "csv":
            return None
        return await contacts_service.organizations_of(
            session, [c.id for c in contacts if not c.is_organization]
        )

    def batch(
        self, contacts: list[Contact], ctx: BuildContext, /
    ) -> tuple[RenderItem, ...]:
        """The spreadsheet is one file however many contacts it holds."""
        if ctx.format != "csv" or not contacts:
            return super().batch(contacts, ctx)
        name = contacts[0].name if len(contacts) == 1 else Tool.contact.plural
        return (
            RenderItem(
                key=export_stem(name, ctx.date),
                data=_table(contacts, ctx.prepared or {}, export_locale(ctx.user)),
            ),
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


def _property_cell(summary: Any, locale: str) -> Any:
    """A property's value as the import reads it back: as the list shows it,
    but a moment in full and a person by handle, which name one exactly."""
    if summary is None:
        return None
    if summary.type in (MetadataType.datetime, MetadataType.user_reference):
        record = property_export_dict(summary)
        return record.get("value_text") or record.get("value_handle")
    return values.property_value(summary, locale, None)


def _table(
    contacts: list[Contact],
    organizations: dict[int, tuple[int, str, int | None]],
    locale: str,
) -> dict[str, Any]:
    columns = [
        values.Column("name", et("contacts.name", locale), lambda c: c.name),
        values.Column(
            "type",
            et("contacts.type", locale),
            lambda c: et(
                "contacts.organization" if c.is_organization else "contacts.person",
                locale,
            ),
        ),
    ]
    for field in DETAILS:
        for n in range(max(len(getattr(contact, field)) for contact in contacts)):
            for part, key in (("value", field), ("label", f"{field}Label")):
                columns.append(
                    values.Column(
                        f"{field}.{n}.{part}",
                        et(f"contacts.{key}", locale, n=n + 1),
                        lambda c, field=field, n=n, part=part: (
                            getattr(c, field)[n].get(part)
                            if n < len(getattr(c, field))
                            else None
                        ),
                    )
                )
    columns += [
        values.Column(
            "organization",
            et("contacts.partOf", locale),
            lambda c: organizations[c.id][1] if c.id in organizations else None,
        ),
        values.Column(
            "tags",
            values.label("tag_ids", locale),
            lambda c: ", ".join(
                sorted((tag.name for tag in annotated_tags(c)), key=str.casefold)
            ),
        ),
    ]
    properties = {
        summary.property_id: summary.name
        for contact in contacts
        for summary in portable_summaries(contact)
    }
    columns += [
        values.Column(
            f"property.{property_id}",
            name,
            lambda c, property_id=property_id: _property_cell(
                next(
                    (s for s in portable_summaries(c) if s.property_id == property_id),
                    None,
                ),
                locale,
            ),
        )
        for property_id, name in properties.items()
    ]
    return {
        "columns": values.head(columns),
        "rows": [values.cells(columns, contact) for contact in contacts],
    }
