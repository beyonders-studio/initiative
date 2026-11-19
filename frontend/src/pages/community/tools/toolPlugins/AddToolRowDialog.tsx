import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { PropertyValueInput } from "@/api/generated/initiativeAPI.schemas";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { type ToolRow, type ToolTable, toolText } from "@/lib/toolPlugins";
import type { DialogProps } from "@/types/dialog";
import type { ItemSaves } from "@/ui/layouts/fieldEditors";

import { type ToolRowUpdate, toolDetail } from "./toolDetail";

/** What a new row is made from: its name, its declared fields' values and the
 *  initiative's properties it is given. */
export interface ToolRowCreate {
  name: string;
  values: Record<string, unknown>;
  properties: PropertyValueInput[];
}

/** A row of `table` not yet added, each field at its declared default and a
 *  counter at where it starts. */
export const blankRow = (table: ToolTable, initiativeId: number): ToolRow => {
  const defaults = Object.fromEntries(
    table.fields.map((field) => [field.key, field.default ?? null])
  );
  const startOf = (initial: number | string | undefined) =>
    typeof initial === "string" ? (defaults[initial] ?? 0) : (initial ?? 0);
  return {
    id: 0,
    initiative_id: initiativeId,
    name: "",
    created_by: 0,
    created_at: "",
    updated_at: "",
    values: Object.fromEntries(
      table.fields.map((field) => [
        field.key,
        field.kind === "counter" ? startOf(field.counter?.initial) : defaults[field.key],
      ])
    ),
    properties: [],
    tags: [],
  };
};

/**
 * Adding a row to a plug-in's table, drawn as the detail layout it declared
 * lays a row out, each field with its kind's editor. Nothing is saved until
 * Add.
 */
export const AddToolRowDialog = ({
  open,
  onOpenChange,
  table,
  initiativeId,
  saves,
  create,
  onAdded,
}: DialogProps & {
  table: ToolTable;
  initiativeId: number;
  /** How a row's fields are saved: while it is being added, into the draft. */
  saves: ItemSaves<ToolRow, ToolRowUpdate>;
  create: (row: ToolRowCreate) => Promise<{ id: number }>;
  onAdded: (made: { id: number }) => void;
}) => {
  const { t, i18n } = useTranslation("plugins");
  const detail = useMemo(() => toolDetail(table, i18n.language), [table, i18n.language]);
  const blank = useMemo(() => blankRow(table, initiativeId), [table, initiativeId]);
  const title = t("tool.create", { name: toolText(table.name, i18n.language) });
  return (
    <AddItemDialog
      open={open}
      onOpenChange={onOpenChange}
      detail={detail}
      blank={blank}
      context={{ readOnly: false, initiativeId, saves, actions: null }}
      // Drawn as the plug-in declared it.
      layouts={() => null}
      title={title}
      ready={(row) => row.name.trim() !== ""}
      // The row as drawn holds every field's value; a field's own change names
      // only its own.
      create={({ item, properties }) =>
        create({ name: item.name.trim(), values: item.values, properties })
      }
      onAdded={onAdded}
    />
  );
};
