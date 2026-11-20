/**
 * A tool plug-in's rows, the tool's own and its items', read and written by
 * kind through the generic routes every tool plug-in shares.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type {
  PluginToolActionRun,
  PluginToolRowCreate,
  PluginToolRowRead,
  PluginToolRowUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPluginToolRow,
  getListPluginToolRowsQueryKey,
  getReadPluginToolRowQueryKey,
  listPluginToolRows,
  runPluginToolAction,
  updatePluginToolRow,
  useReadPluginToolRow,
} from "@/api/generated/plugin-tools/plugin-tools";
import { invalidate, type Spec } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { type InstalledTool, installedTools, type ToolRow } from "@/lib/toolPlugins";

/** The tools the community's tool plug-ins declare, as far as they are known:
 *  still being read, unread for a failure, or read. */
export type InstalledTools =
  | { status: "loading" }
  | { status: "error"; retry: () => void }
  | { status: "ready"; tools: InstalledTool[] };

/** The tools the community's tool plug-ins declare, from the installs every
 *  member reads. A reader the installs are not read for has none. */
export const useInstalledTools = (): InstalledTools => {
  const { data, isError, isLoading, refetch } = useCommunityPlugins();
  const tools = useMemo(() => (data ? installedTools(data.items) : []), [data]);
  if (data) return { status: "ready", tools };
  if (isError) return { status: "error", retry: () => void refetch() };
  return isLoading ? { status: "loading" } : { status: "ready", tools };
};

/** Every read of one kind's rows: its lists and each row. */
const rowsOf = (kind: string): Spec => ({
  communityPrefix: [`/api/v1/plugin-tools/${kind}/`],
});

/** Every row of `kind` in one place, the tool's own in an initiative or an
 *  item table's under one row: `page_size: 0` walks the server's windows, so
 *  a preset sorts all of them. */
export const usePluginToolRows = (
  kind: string,
  where: { initiative_id: number } | { parent_id: number }
) => {
  const communityId = useActiveCommunityId();
  const params = { ...where, page_size: 0 };
  return useQuery({
    queryKey: getListPluginToolRowsQueryKey(communityId, kind, params),
    queryFn: () => fetchAllPages((p) => listPluginToolRows(communityId, kind, p), params),
  });
};

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
