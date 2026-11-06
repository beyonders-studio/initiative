import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { at, detailLayoutSpec, type Region } from "./detailLayout";
import type { FieldDef, FieldKind } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** An event's fields, each with its label's key and the kind of value it is. */
export const EVENT_FIELDS = {
  title: { label: "calendars:eventTitle", kind: "title" },
  description: { label: "calendars:eventPage.description", kind: "excerpt" },
  location: { label: "calendars:location", kind: "excerpt" },
  recurrence: { label: "calendars:repeat", kind: "recurrence" },
  attendees: { label: "calendars:attendees", kind: "people" },
  tags: { label: "common:toolSettings.tags", kind: "tags" },
} as const satisfies Record<string, { label: string; kind: FieldKind }>;

/** What a person fills in on an event, beside its title, which every event
 *  has. */
const EVENT_REQUIREABLE: ReadonlySet<string> = new Set([
  "description",
  "location",
  "recurrence",
  "attendees",
  "tags",
]);

/** An event's fields as the editor names them, then the initiative's
 *  properties. An event is drawn in its detail alone so far, so none has a
 *  value to draw elsewhere. */
export const eventFields = (
  definitions: PropertyDefinitionRead[] = [],
  plugins: FieldDef[] = []
): Map<string, FieldDef> =>
  new Map(
    [
      ...Object.entries(EVENT_FIELDS).map(
        ([id, { label, kind }]): FieldDef => ({
          id,
          kind,
          label,
          source: "builtin",
          hideable: id !== "title",
          requireable: EVENT_REQUIREABLE.has(id),
          value: () => null,
        })
      ),
      ...propertyFields(definitions, () => null),
      ...plugins,
    ].map((field) => [field.id, field])
  );

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/**
 * An event's detail as shipped: its title and what else can be done with it
 * across the top; what it is and who is coming in the main column; and when
 * and where it is, with its tags and properties, beside them. On one column
 * it reads as the event's detail always has: the description, when and where,
 * your answer, who is coming, tags, relations, then properties.
 */
const EVENT_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("title"), { type: "actions" }],
    },
  ],
  main: [
    at(1, { type: "section", children: [field("description")] }),
    at(3, { type: "rsvp" }),
    at(4, { type: "section", children: [field("attendees")] }),
    at(6, { type: "relations" }),
  ],
  side: [
    at(2, {
      type: "section",
      children: [{ type: "dates" }, field("recurrence"), field("location")],
    }),
    at(5, { type: "section", children: [field("tags")] }),
    at(7, { type: "section", children: [{ type: "properties" }] }),
  ],
};

/** An event's detail: its dates and properties edit fields as a field does. */
export const EVENT_LAYOUT = detailLayoutSpec({
  kind: "calendar_event",
  shipped: EVENT_DETAIL_REGIONS,
  fieldParts: ["field", "dates", "properties"],
  // Its dates are never empty.
  requiredParts: [],
});
