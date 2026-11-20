/**
 * A tool plug-in's rows, the tool's own and its items', read and written by
 * kind through the generic routes every tool plug-in shares.
 */

import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";

import type {
  PluginToolActionRun,
  PluginToolRowCreate,
  PluginToolRowRead,
  PluginToolRowUpdate,
  PluginToolStep,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPluginToolRow,
  deletePluginToolRow,
  getListPluginToolRowsQueryKey,
  getReadPluginToolRowQueryKey,
  listPluginToolRows,
  runPluginToolAction,
  stepPluginToolRow,
  updatePluginToolRow,
  useReadPluginToolRow,
} from "@/api/generated/plugin-tools/plugin-tools";
import { bulkSetResourceGrants } from "@/api/generated/resource-grants/resource-grants";
import { invalidate, q } from "@/api/query-keys";
import type { GrantsChange } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import { fetchAllPages } from "@/lib/fetchAllPages";
import type { ToolRow, ToolTable } from "@/lib/toolPlugins";
import type { MutationOpts } from "@/types/mutation";
import type { LayoutEnv } from "@/ui/layouts/fields";

/** Every row of `table` in one place, the tool's own in an initiative or an
 *  item table's under one row, live or archived, each with what its card
 *  previews of the items under it: `page_size: 0` walks the server's
 *  windows, so a preset sorts all of them. */
export const usePluginToolRows = (
  { kind, items }: Pick<ToolTable, "kind" | "items">,
  where: ({ initiative_id: number } | { parent_id: number }) & { archived?: true }
) => {
  const communityId = useActiveCommunityId();
  const params = { ...where, ...(items.length > 0 ? { include_preview: true } : {}), page_size: 0 };
  return useQuery({
    queryKey: getListPluginToolRowsQueryKey(communityId, kind, params),
    queryFn: () => fetchAllPages((p) => listPluginToolRows(communityId, kind, p), params),
  });
};

export const usePluginToolRow = (kind: string, rowId: number | null) =>
  useReadPluginToolRow(useActiveCommunityId(), kind, rowId ?? 0, {
    query: { enabled: rowId !== null },
  });

/** Adds a row. A row over it previews its items, so every tool plug-in row
 *  is read again, as after every write here. */
export const useCreatePluginToolRow = (kind: string) =>
  useCommunityMutation<PluginToolRowRead, PluginToolRowCreate>({
    mutationFn: (communityId, data) => createPluginToolRow(communityId, kind, data),
    invalidate: () => invalidate(q.pluginToolRows()),
    errorKey: "plugins:error",
  });

/** Runs one of a table's actions on a row. What it writes may reach the rows
 *  under it and over it. */
export const useRunPluginToolAction = (kind: string) =>
  useCommunityMutation<
    PluginToolRowRead,
    { rowId: number; actionId: string } & PluginToolActionRun
  >({
    mutationFn: (communityId, { rowId, actionId, ...run }) =>
      runPluginToolAction(communityId, kind, rowId, actionId, run),
    invalidate: () => invalidate(q.pluginToolRows()),
    errorKey: "plugins:error",
  });

/** How a list steps the counter fields of a table's rows: a row's, where
 *  its reader may change it, as the row's own page would (an edit of the
 *  tool's own row, contributing to it for an item's). Answers the field's
 *  value as the row then holds it. A step shows wherever the row is listed,
 *  so every tool plug-in row is read again. */
export const usePluginToolSteps = () => {
  const { mutateAsync } = useCommunityMutation<
    PluginToolRowRead,
    { kind: string; rowId: number } & PluginToolStep
  >({
    mutationFn: (communityId, { kind, rowId, ...step }) =>
      stepPluginToolRow(communityId, kind, rowId, step),
    invalidate: () => invalidate(q.pluginToolRows()),
    errorKey: "plugins:error",
  });
  return useCallback(
    (table: Pick<ToolTable, "kind" | "parent">): NonNullable<LayoutEnv<ToolRow>["stepCounter"]> =>
      (row, summary) => {
        const { key } = summary;
        const may = table.parent === null ? row.can.edit : row.can.contribute;
        return key && may
          ? async (up) => {
              const read = await mutateAsync({
                kind: table.kind,
                rowId: row.id,
                field: key,
                ...(up ? {} : { down: true }),
              });
              return [{ ...summary, value: read.fields[key] ?? null }];
            }
          : null;
      },
    [mutateAsync]
  );
};

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
 *  initiative's properties; a row over it previews it, so every list of a
 *  tool plug-in's rows is read again. */
export const pluginToolRowSaves = (kind: string): FieldSaveKind<ToolRow, PluginToolRowUpdate> => ({
  name: `plugin-tool-${kind}`,
  readKey: (communityId, id) => getReadPluginToolRowQueryKey(communityId, kind, id),
  patch: (communityId, id, patch) => updatePluginToolRow(communityId, kind, id, patch),
  lists: () => q.pluginToolRows(),
  itself: () => q.pluginToolRows(kind),
});
