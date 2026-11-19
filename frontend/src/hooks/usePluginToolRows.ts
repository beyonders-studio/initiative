/**
 * A tool plug-in's rows, the tool's own and its items', read and written by
 * kind through the generic routes every tool plug-in shares.
 */

import { useMemo } from "react";

import type {
  PluginToolActionRun,
  PluginToolRowCreate,
  PluginToolRowRead,
  PluginToolRowUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPluginToolRow,
  getReadPluginToolRowQueryKey,
  runPluginToolAction,
  updatePluginToolRow,
  useListPluginToolRows,
  useReadPluginToolRow,
} from "@/api/generated/plugin-tools/plugin-tools";
import { invalidate, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import { type InstalledTool, installedTools, type ToolRow } from "@/lib/toolPlugins";

/** The tools the community's tool plug-ins declare, from the installs every
 *  member reads; undefined until they are read. */
export const useInstalledTools = (): InstalledTool[] | undefined => {
  const { data } = useCommunityPlugins();
  return useMemo(() => (data ? installedTools(data.items) : undefined), [data]);
};

/** Every read of one kind's rows: its lists and each row. */
const rowsOf = (kind: string): Spec => ({
  communityPrefix: [`/api/v1/plugin-tools/${kind}/`],
});

/** The rows of `kind` in one place: the tool's own in an initiative, or an
 *  item table's under one row. */
export const usePluginToolRows = (
  kind: string,
  where: { initiative_id: number } | { parent_id: number }
) => useListPluginToolRows(useActiveCommunityId(), kind, { ...where, page_size: 100 });

export const usePluginToolRow = (kind: string, rowId: number | null) =>
  useReadPluginToolRow(useActiveCommunityId(), kind, rowId ?? 0, {
    query: { enabled: rowId !== null },
  });

export const useCreatePluginToolRow = (kind: string) =>
  useCommunityMutation<PluginToolRowRead, PluginToolRowCreate>({
    mutationFn: (communityId, data) => createPluginToolRow(communityId, kind, data),
    invalidate: () => invalidate(rowsOf(kind)),
    errorKey: "plugins:error",
  });

/** Runs one of a table's actions on a row. What it writes may reach the rows
 *  under it, so every read of the tool is read again. */
export const useRunPluginToolAction = (kind: string, itemKinds: readonly string[]) =>
  useCommunityMutation<
    PluginToolRowRead,
    { rowId: number; actionId: string } & PluginToolActionRun
  >({
    mutationFn: (communityId, { rowId, actionId, ...run }) =>
      runPluginToolAction(communityId, kind, rowId, actionId, run),
    invalidate: () => invalidate(rowsOf(kind), ...itemKinds.map(rowsOf)),
    errorKey: "plugins:error",
  });

/** How a row of `kind` is saved field by field. Its rows hold none of the
 *  initiative's properties. */
export const pluginToolRowSaves = (kind: string): FieldSaveKind<ToolRow, PluginToolRowUpdate> => ({
  name: `plugin-tool-${kind}`,
  readKey: (communityId, id) => getReadPluginToolRowQueryKey(communityId, kind, id),
  patch: (communityId, id, patch) => updatePluginToolRow(communityId, kind, id, patch),
  lists: () => rowsOf(kind),
  itself: () => rowsOf(kind),
});
