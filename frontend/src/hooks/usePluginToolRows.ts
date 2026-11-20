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
  deletePluginToolRow,
  getListPluginToolRowsQueryKey,
  getReadPluginToolRowQueryKey,
  listPluginToolRows,
  runPluginToolAction,
  updatePluginToolRow,
  useReadPluginToolRow,
} from "@/api/generated/plugin-tools/plugin-tools";
import { bulkSetResourceGrants } from "@/api/generated/resource-grants/resource-grants";
import { invalidate, q } from "@/api/query-keys";
import type { GrantsChange } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { type InstalledTool, installedTools, type ToolRow } from "@/lib/toolPlugins";
import type { MutationOpts } from "@/types/mutation";

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

/** Every row of `kind` in one place, the tool's own in an initiative or an
 *  item table's under one row, live or archived: `page_size: 0` walks the
 *  server's windows, so a preset sorts all of them. */
export const usePluginToolRows = (
  kind: string,
  where: ({ initiative_id: number } | { parent_id: number }) & { archived?: true }
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
    invalidate: () => invalidate(q.pluginToolRows(kind)),
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
    invalidate: () => invalidate(q.pluginToolRows(kind), ...itemKinds.map(q.pluginToolRows)),
    errorKey: "plugins:error",
  });

/** Puts a row in the trash, with the items under it. The rows over it list
 *  it no more, so every tool plug-in row is read again. */
export const useDeletePluginToolRow = (kind: string, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, rowId) => deletePluginToolRow(communityId, kind, rowId),
      invalidate: () => invalidate(q.pluginToolRows()),
      errorKey: "plugins:error",
    },
    options
  );

/** Replaces who a tool's row is shared with, as the sharing panel answers
 *  it. Its items answer to its sharing, so each is read again too. */
export const useSetPluginToolRowGrants = (kind: string, rowId: number) =>
  useCommunityMutation<void, GrantsChange>({
    mutationFn: async (communityId, { grants, note }) => {
      const { results } = await bulkSetResourceGrants(communityId, {
        items: [{ resource_type: kind, resource_id: rowId, grants }],
        note,
      });
      // One row, so a row it skipped is this change refused.
      if (results[0]?.status !== "ok") throw new Error(results[0]?.detail ?? "");
    },
    invalidate: () => invalidate(q.pluginToolRows()),
    errorKey: "access:bulkAccess.updateError",
  });

/** How a row of `kind` is saved field by field. Its rows hold none of the
 *  initiative's properties. */
export const pluginToolRowSaves = (kind: string): FieldSaveKind<ToolRow, PluginToolRowUpdate> => ({
  name: `plugin-tool-${kind}`,
  readKey: (communityId, id) => getReadPluginToolRowQueryKey(communityId, kind, id),
  patch: (communityId, id, patch) => updatePluginToolRow(communityId, kind, id, patch),
  lists: () => q.pluginToolRows(kind),
  itself: () => q.pluginToolRows(kind),
});
