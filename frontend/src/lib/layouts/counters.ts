import type { PropertyDefinitionRead } from "@/api/generated/initiativeAPI.schemas";

import { at, detailLayoutSpec, type Region } from "./detailLayout";
import type { FieldDef, FieldKind } from "./fields";
import { propertyFields } from "./tasks";
import type { LayoutNode } from "./tree";

/** A counter's fields, each with its label's key and the kind of value it is.
 *  It is drawn in its detail alone, so no kind draws it anywhere else. */
export const COUNTER_FIELDS = {
  name: { label: "common:name", kind: "title" },
  color: { label: "counterGroups:color", kind: "excerpt" },
  min: { label: "counterGroups:min", kind: "count" },
  max: { label: "counterGroups:max", kind: "count" },
  step: { label: "counterGroups:step", kind: "count" },
  start: { label: "counterGroups:initialCount", kind: "count" },
  view: { label: "counterGroups:viewMode", kind: "excerpt" },
} as const satisfies Record<string, { label: string; kind: FieldKind }>;

/** A counter's fields as the editor names them, then the initiative's
 *  properties, then the plug-ins'. */
export const counterFields = (
  definitions: PropertyDefinitionRead[] = [],
  plugins: FieldDef[] = []
): Map<string, FieldDef> =>
  new Map(
    [
      ...Object.entries(COUNTER_FIELDS).map(
        ([id, { label, kind }]): FieldDef => ({
          id,
          kind,
          label,
          source: "builtin",
          hideable: id !== "name",
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
 * A counter's detail as shipped: its name and what else can be done with it
 * across the top; its count and what is linked to it in the main column; and
 * how it counts and its properties beside them.
 */
const COUNTER_DETAIL_REGIONS: Record<Region, LayoutNode[]> = {
  header: [
    {
      type: "stack",
      props: { direction: "row", gap: "sm", align: "start" },
      children: [field("name"), { type: "actions" }],
    },
  ],
  main: [at(1, { type: "count" }), at(4, { type: "relations" })],
  side: [
    at(2, {
      type: "section",
      children: [
        field("color"),
        field("min"),
        field("max"),
        field("step"),
        field("start"),
        field("view"),
      ],
    }),
    at(3, { type: "section", children: [{ type: "properties" }] }),
  ],
};

/** A counter's detail: its properties edit fields as a field does. */
export const COUNTER_LAYOUT = detailLayoutSpec({
  kind: "counter",
  shipped: COUNTER_DETAIL_REGIONS,
  fieldParts: ["field", "properties"],
});
