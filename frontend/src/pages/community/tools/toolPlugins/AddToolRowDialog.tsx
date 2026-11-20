import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ActorKind, type PluginToolRowCreate } from "@/api/generated/initiativeAPI.schemas";
import { AddItemDialog } from "@/components/layouts/AddItemDialog";
import { itemSaves } from "@/hooks/useFieldSave";
import { pluginToolRowSaves, useCreatePluginToolRow } from "@/hooks/usePluginToolRows";
import {
  fieldChange,
  fieldStart,
  fieldValue,
  type ToolRow,
  type ToolTable,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import type { DialogProps } from "@/types/dialog";
import { sameJson } from "@/ui/layouts/editing";

import { toolDetail } from "./toolDetail";

/** A row of `table` not yet added, each field shown as the server starts it. */
export const blankRow = (table: ToolTable, initiativeId: number): ToolRow => {
  const start = table.fields.map((field) => fieldChange(field, fieldStart(table.fields, field)));
  return toolRow({
    kind: table.kind,
    id: 0,
    community_id: 0,
    initiative_id: initiativeId,
    parent_id: null,
    name: "",
    position: 0,
    fields: Object.assign({}, ...start.map((change) => change.fields)),
    people: Object.assign({}, ...start.map((change) => change.people)),
    created_by: null,
    created_by_kind: ActorKind.member,
    created_by_install: null,
    archived_at: null,
    can: { edit: true, contribute: true, delete: true, share: true, export: true, unarchive: true },
    comments_enabled: true,
    grants: [],
    tags: [],
    created_at: "",
    updated_at: "",
    preview: null,
  });
};

/** The fields `item` holds otherwise than `blank`: the ones the person set. */
export const setOn = (
  table: ToolTable,
  blank: ToolRow,
  item: ToolRow
): Required<Pick<PluginToolRowCreate, "fields" | "people">> => {
  const changes = table.fields
    .filter((field) => !sameJson(fieldValue(item, field), fieldValue(blank, field)))
    .map((field) => fieldChange(field, fieldValue(item, field)));
  return {
    fields: Object.assign({}, ...changes.map((change) => change.fields)),
    people: Object.assign({}, ...changes.map((change) => change.people)),
  };
};

/**
 * Adding a row to a plug-in's table, drawn as the detail layout it declared
 * lays a row out, each field with its kind's editor. Nothing is saved until
 * Add, which makes it in the initiative or under the row it is an item of.
 */
export const AddToolRowDialog = ({
  open,
  onOpenChange,
  table,
  initiativeId,
  parentId,
  onAdded,
}: DialogProps & {
  table: ToolTable;
  initiativeId: number;
  /** The row it is an item of; none for one of the tool's own. */
  parentId?: number;
  onAdded: (made: ToolRow) => void;
}) => {
  const { t, i18n } = useTranslation("plugins");
  const detail = useMemo(() => toolDetail(table, i18n.language), [table, i18n.language]);
  const blank = useMemo(() => blankRow(table, initiativeId), [table, initiativeId]);
  // While it is being added its fields' saves change the draft alone.
  const saves = useMemo(() => itemSaves(pluginToolRowSaves(table.kind), 0), [table.kind]);
  const create = useCreatePluginToolRow(table.kind);
  return (
    <AddItemDialog
      open={open}
      onOpenChange={onOpenChange}
      detail={detail}
      blank={blank}
      context={{ readOnly: false, initiativeId, saves, actions: null }}
      // Drawn as the plug-in declared it.
      layouts={() => null}
      title={t("tool.create", { name: toolText(table.name, i18n.language) })}
      ready={(row) => row.name.trim() !== ""}
      // Only what the person set is sent, so the server starts the rest.
      create={async ({ item }) =>
        toolRow(
          await create.mutateAsync({
            name: item.name.trim(),
            ...setOn(table, blank, item),
            ...(item.tags.length > 0 ? { tag_ids: item.tags.map((tag) => tag.id) } : {}),
            ...(parentId === undefined ? { initiative_id: initiativeId } : { parent_id: parentId }),
          })
        )
      }
      onAdded={onAdded}
    />
  );
};
