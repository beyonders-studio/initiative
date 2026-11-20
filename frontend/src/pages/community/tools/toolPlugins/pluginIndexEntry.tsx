import { useMemo } from "react";

import { usePluginToolRows } from "@/hooks/usePluginToolRows";
import { type InstalledTool, type ToolTable, toolRow } from "@/lib/toolPlugins";
import type {
  ToolIndexCreateDialogProps,
  ToolIndexEntry,
  ToolIndexList,
} from "@/pages/community/tools/ToolIndexPage";
import { sameJson } from "@/ui/layouts/editing";

import { AddToolRowDialog } from "./AddToolRowDialog";

const entries = new Map<string, ToolIndexEntry>();

/**
 * A tool plug-in's tool, as the index page lists it: a page of its own rows
 * in an initiative, narrowed, sorted and paged by the server as a built-in
 * tool's are, drawn in the lists its table declares, and added to with the
 * dialog its detail lays out. One entry per table while it is declared the
 * same, so a refresh of the installs keeps the page's hooks and an open add
 * dialog.
 */
export const pluginIndexEntry = (tool: InstalledTool, table: ToolTable): ToolIndexEntry => {
  const known = entries.get(table.kind);
  if (known?.laidOut && sameJson([...known.laidOut.tool.tables], [...tool.tables])) return known;
  const CreateDialog = ({
    open,
    onOpenChange,
    initiativeId,
    onSuccess,
  }: ToolIndexCreateDialogProps) => (
    <AddToolRowDialog
      open={open}
      onOpenChange={onOpenChange}
      table={table}
      initiativeId={initiativeId}
      onAdded={onSuccess}
    />
  );
  const entry: ToolIndexEntry = {
    useList: (initiativeId, filters): ToolIndexList => {
      const query = usePluginToolRows(table, {
        // A tool plug-in's rows are all an initiative's.
        initiative_id: initiativeId ?? 0,
        ...filters.view,
        ...filters.sort,
        search: filters.list.search,
        tag_ids: filters.list.tag_ids,
        page: filters.page,
        page_size: filters.pageSize,
      });
      const rows = useMemo(
        () => (query.data?.items ?? []).map((read) => ({ ...toolRow(read), card: null })),
        [query.data]
      );
      return {
        rows,
        isLoading: query.isLoading,
        isError: query.isError,
        refetch: query.refetch,
        isPlaceholderData: query.isPlaceholderData,
        totalCount: query.data?.total_count ?? 0,
        hasNext: query.data?.has_next ?? false,
      };
    },
    text: {
      create: "tool.create",
      noMatches: "tool.noMatches",
      emptyTitle: "tool.empty",
      emptyBody: "tool.emptyBody",
      createFirst: "tool.createFirst",
      search: "filters.search",
    },
    CreateDialog,
    laidOut: { tool, table },
  };
  entries.set(table.kind, entry);
  return entry;
};
