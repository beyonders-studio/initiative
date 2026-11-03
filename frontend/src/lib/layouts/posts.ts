import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { at, detailLayoutSpec, type Region } from "./detailLayout";
import type { FieldDef, FieldKind } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** A notice's fields, each with its label's key and the kind of value it is.
 *  Its title, tags and properties are changed in its tool's header; here its
 *  tags are drawn where the layout puts them. */
export const POST_FIELDS = {
  tags: { label: "common:toolSettings.tags", kind: "tags" },
} as const satisfies Record<string, { label: string; kind: FieldKind }>;

/** A notice's fields as the editor names them, then the initiative's
 *  properties, then the plug-ins'. */
export const postFields = (
  definitions: PropertyDefinitionRead[] = [],
  plugins: FieldDef[] = []
): Map<string, FieldDef> =>
  new Map(
    [
      ...Object.entries(POST_FIELDS).map(
        ([id, { label, kind }]): FieldDef => ({
          id,
          kind,
          label,
          source: "builtin",
          hideable: true,
          requireable: true,
          value: () => null,
        })
      ),
      ...propertyFields(definitions, () => null),
      ...plugins,
    ].map((field) => [field.id, field])
  );

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/**
 * A notice's detail as shipped: who wrote it and when it goes up across the
 * top; what it says, its reactions, tags and comments in the main column; and
 * what it asks and what it is linked to beside them. On one column it reads
 * as the notice always has.
 */
const POST_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [{ type: "byline" }, { type: "schedule" }],
  main: [
    at(1, { type: "body" }),
    at(2, { type: "reactions" }),
    at(3, field("tags")),
    at(6, { type: "comments" }),
  ],
  side: [at(4, { type: "poll" }), at(5, { type: "relations" })],
};

/** A notice's detail: its properties edit fields as a field does. */
export const POST_LAYOUT = detailLayoutSpec({
  kind: "post",
  shipped: POST_DETAIL_REGIONS,
  fieldParts: ["field", "properties"],
  requiredParts: [],
});
