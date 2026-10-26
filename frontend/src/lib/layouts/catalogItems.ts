import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { at, detailLayoutSpec, type Region } from "./detailLayout";
import type { FieldDef, FieldKind } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** A picture's fields, each with its label's key and the kind of value it is.
 *  It is drawn in its detail alone, so no kind draws it anywhere else. */
export const CATALOG_ITEM_FIELDS = {
  title: { label: "catalogs:sheet.titleLabel", kind: "title" },
  caption: { label: "catalogs:sheet.caption", kind: "excerpt" },
  tags: { label: "catalogs:sheet.tags", kind: "tags" },
} as const satisfies Record<string, { label: string; kind: FieldKind }>;

/** A picture's fields as the editor names them, then the initiative's
 *  properties, then the plug-ins'. */
export const catalogItemFields = (
  definitions: PropertyDefinitionRead[] = [],
  plugins: FieldDef[] = []
): Map<string, FieldDef> =>
  new Map(
    [
      ...Object.entries(CATALOG_ITEM_FIELDS).map(
        ([id, { label, kind }]): FieldDef => ({
          id,
          kind,
          label,
          source: "builtin",
          hideable: id !== "title",
          value: () => null,
        })
      ),
      ...propertyFields(definitions, () => null),
      ...plugins,
    ].map((field) => [field.id, field])
  );

const field = (id: string): LayoutNode => ({ type: "field", props: { field: id } });

/**
 * A picture's detail as shipped: what it is called and what else can be done
 * with it across the top; the picture, what is said about it and what is
 * linked to it in the main column; and its tags, properties, where it came
 * from and its versions beside them.
 */
const CATALOG_ITEM_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("title"), { type: "actions" }],
    },
  ],
  main: [
    at(1, { type: "picture" }),
    at(2, { type: "section", children: [field("caption")] }),
    at(6, { type: "relations" }),
  ],
  side: [
    at(3, { type: "section", children: [field("tags"), { type: "properties" }] }),
    at(4, { type: "about" }),
    at(5, { type: "versions" }),
  ],
};

/** A picture's detail: its properties edit fields as a field does. */
export const CATALOG_ITEM_LAYOUT = detailLayoutSpec({
  kind: "catalog_item",
  shipped: CATALOG_ITEM_DETAIL_REGIONS,
  fieldParts: ["field", "properties"],
});
