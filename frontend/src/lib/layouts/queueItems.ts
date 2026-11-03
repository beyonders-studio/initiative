import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { at, detailLayoutSpec, type Region } from "./detailLayout";
import type { FieldDef, FieldKind } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** A queue item's fields, each with its label's key and the kind of value it
 *  is. It is drawn in its detail alone, so no kind draws it anywhere else. */
export const QUEUE_ITEM_FIELDS = {
  label: { label: "queues:label", kind: "title" },
  notes: { label: "queues:notes", kind: "excerpt" },
  position: { label: "queues:position", kind: "count" },
  color: { label: "queues:color", kind: "excerpt" },
  visible: { label: "queues:visible", kind: "excerpt" },
  person: { label: "queues:linkedUser", kind: "people" },
  tags: { label: "queues:tags", kind: "tags" },
} as const satisfies Record<string, { label: string; kind: FieldKind }>;

/** A queue item's fields as the editor names them, then the initiative's
 *  properties, then the plug-ins'. */
export const queueItemFields = (
  definitions: PropertyDefinitionRead[] = [],
  plugins: FieldDef[] = []
): Map<string, FieldDef> =>
  new Map(
    [
      ...Object.entries(QUEUE_ITEM_FIELDS).map(
        ([id, { label, kind }]): FieldDef => ({
          id,
          kind,
          label,
          source: "builtin",
          hideable: id !== "label",
          requireable: false,
          value: () => null,
        })
      ),
      ...propertyFields(definitions, () => null),
      ...plugins,
    ].map((field) => [field.id, field])
  );

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/**
 * A queue item's detail as shipped: its label and what else can be done with
 * it across the top; its notes and what is linked to it in the main column;
 * and where it stands in the queue, who it is for, its tags and properties
 * beside them.
 */
const QUEUE_ITEM_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("label"), { type: "actions" }],
    },
  ],
  main: [at(1, { type: "section", children: [field("notes")] }), at(5, { type: "relations" })],
  side: [
    at(2, {
      type: "section",
      children: [field("person"), field("position"), field("color"), field("visible")],
    }),
    at(3, { type: "section", children: [field("tags")] }),
    at(4, { type: "section", children: [{ type: "properties" }] }),
  ],
};

/** A queue item's detail: its properties edit fields as a field does. */
export const QUEUE_ITEM_LAYOUT = detailLayoutSpec({
  kind: "queue_item",
  shipped: QUEUE_ITEM_DETAIL_REGIONS,
  fieldParts: ["field", "properties"],
});
