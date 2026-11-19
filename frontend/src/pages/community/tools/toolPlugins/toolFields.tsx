/**
 * What a tool plug-in's layouts name: the fields every tool row has, and the
 * fields its table declares, each drawn in its kind's look.
 */

import type { MetadataType } from "@/api/generated/initiativeAPI.schemas";
import { TagBadgeList } from "@/components/tags/TagBadge";
import {
  fieldSummary,
  type ToolFieldDecl,
  type ToolRow,
  type ToolTable,
  toolText,
} from "@/lib/toolPlugins";
import type { FieldDef, FieldRendererProps } from "@/ui/layouts/fields";
import { iconForPropertyType } from "@/ui/properties/propertyTypeIcons";

/** A colour: its swatch, named for whoever cannot see it. */
const ColorSwatch = ({ value }: FieldRendererProps<ToolRow>) => (
  <span
    className="inline-block h-4 w-4 shrink-0 rounded-full border"
    style={{ backgroundColor: String(value) }}
    title={String(value)}
  >
    <span className="sr-only">{String(value)}</span>
  </span>
);

const Tags = ({ item }: FieldRendererProps<ToolRow>) => <TagBadgeList tags={item.tags} />;

/** The fields every tool row has, as a layout names them. */
const universal = (): FieldDef<ToolRow>[] => [
  {
    id: "name",
    kind: "title",
    source: "builtin",
    label: "common:name",
    hideable: false,
    requireable: false,
    value: (row) => row.name,
  },
  {
    id: "created_at",
    kind: "date",
    source: "builtin",
    label: "plugins:tool.fields.createdAt",
    hideable: true,
    requireable: false,
    value: (row) => row.created_at,
  },
  {
    id: "updated_at",
    kind: "date",
    source: "builtin",
    label: "plugins:tool.fields.updatedAt",
    hideable: true,
    requireable: false,
    value: (row) => row.updated_at,
  },
  {
    id: "tags",
    render: Tags,
    source: "builtin",
    label: "common:toolSettings.tags",
    hideable: true,
    requireable: false,
    value: (row) => row.tags,
  },
];

/** One declared field: a colour as its swatch, anything else as the kit draws
 *  a property of its kind. */
const declared = (field: ToolFieldDecl, language: string): FieldDef<ToolRow> => {
  const label = toolText(field.name, language);
  const base = {
    id: field.key,
    source: "plugin" as const,
    label,
    hideable: true,
    requireable: field.kind !== "counter" && field.kind !== "checkbox",
  };
  if (field.kind === "color") {
    return { ...base, render: ColorSwatch, value: (row) => row.values[field.key] ?? null };
  }
  return {
    ...base,
    kind: "property",
    icon: iconForPropertyType(field.kind as MetadataType),
    // The kit draws a property from its summary, which carries its value.
    value: (row) => {
      const summary = fieldSummary(field, row, language);
      return summary.value === null ? null : summary;
    },
  };
};

/** Every field a table's layouts may name, by id: the universal ones, then
 *  its own in the order it declares them. */
export const toolFields = (
  table: ToolTable,
  language: string
): ReadonlyMap<string, FieldDef<ToolRow>> =>
  new Map(
    [...universal(), ...table.fields.map((field) => declared(field, language))].map((field) => [
      field.id,
      field,
    ])
  );
