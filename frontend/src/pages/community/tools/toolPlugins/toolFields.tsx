/**
 * What a tool plug-in's layouts name: the fields every tool row has, and the
 * fields its table declares, each drawn in its kind's look.
 */

import { useTranslation } from "react-i18next";

import { ActorKind, MetadataType } from "@/api/generated/initiativeAPI.schemas";
import { useActorName } from "@/hooks/useActorName";
import {
  fieldSummary,
  fieldValue,
  type ToolFieldDecl,
  type ToolRow,
  type ToolTable,
  toolText,
} from "@/lib/toolPlugins";
import type { FieldDef, FieldRendererProps } from "@/ui/layouts/fields";
import { PropertyValueCell } from "@/ui/properties/PropertyValueCell";
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

/** Who added a row, as a built-in tool's byline names them: a member as a
 *  person field draws one, a plug-in or the system by its name. */
const Creator = ({ item, field, variant, env }: FieldRendererProps<ToolRow>) => {
  const { i18n } = useTranslation();
  const actorName = useActorName();
  const member = item.created_by_kind === ActorKind.member;
  const summary = fieldSummary(
    {
      key: field.id,
      name: { [i18n.language]: env.t(field.label) },
      kind: member ? "user_reference" : "text",
    },
    item,
    i18n.language
  );
  return (
    <PropertyValueCell
      summary={{
        ...summary,
        value: member ? item.created_by : actorName(item.created_by_kind, item.created_by_install),
      }}
      variant={variant === "cell" ? "cell" : "chip"}
    />
  );
};

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
    id: "created_by",
    render: Creator,
    source: "builtin",
    label: "plugins:tool.fields.createdBy",
    icon: iconForPropertyType(MetadataType.user_reference),
    hideable: true,
    requireable: false,
    // A member by id; whoever else added it by their kind.
    value: (row) =>
      row.created_by_kind === ActorKind.member ? row.created_by : row.created_by_kind,
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
    return { ...base, render: ColorSwatch, value: (row) => fieldValue(row, field) };
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
