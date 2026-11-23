import type { SortingState } from "@tanstack/react-table";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { usePluginToolSteps } from "@/hooks/usePluginToolRows";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type InstalledTool,
  type ToolRow,
  type ToolTable,
  toolPluginRowRoute,
} from "@/lib/toolPlugins";
import type { TranslateFn } from "@/types/i18n";
import { Card, CardContent } from "@/ui/card";
import { DataTable } from "@/ui/data-table";
import { fieldColumn } from "@/ui/layouts/columns";
import { indexPaths } from "@/ui/layouts/draft";
import { type ItemPreview, type LayoutEnv, withDisplays } from "@/ui/layouts/fields";
import type { ListView } from "@/ui/layouts/layoutSet";
import { sortedItems } from "@/ui/layouts/presets";
import { type LayoutContext, type LayoutNode, LayoutTree } from "@/ui/layouts/tree";

import { SelectableGridItem } from "../SelectableGridItem";
import { toolFields } from "./toolFields";

/** What a grid draws where its layout names no card: the row's name. */
export const NAME_CARD: LayoutNode = {
  type: "card",
  children: [{ type: "field", props: { field: "name" } }],
};

/**
 * A table's rows, drawn as one of its lists says: a grid or a masonry wall of
 * its card, or a table of its columns, each field in its kind's look and each
 * scale or counter as the list's `displays` say. A row's name opens its page.
 * They are drawn in `sorting`'s order, a view that never moves the rows' own
 * order; a table's headers change it. A counter steps where its reader may
 * change the row, and a card's `items` part previews the first items under
 * its row as the list read them (`include_preview`), each drawn as their
 * table's first list draws it. With `editing`, as the layout editor draws
 * them, each part of the card is marked and nothing steps.
 */
export const ToolRows = <R extends ToolRow>({
  tool,
  table,
  list,
  rows,
  initiativeId,
  sorting,
  onSortingChange,
  editing = false,
  selection,
}: {
  tool: InstalledTool;
  table: ToolTable;
  list: ListView;
  rows: R[];
  initiativeId: number;
  sorting: SortingState;
  onSortingChange: (sorting: SortingState) => void;
  editing?: boolean;
  /** Picking cards out of a grid or a wall, as a built-in tool's list does. */
  selection?: {
    active: boolean;
    selectedIds: ReadonlySet<number>;
    toggle: (row: R, options?: GridToggleOptions) => void;
  };
}) => {
  const { t, i18n } = useTranslation(["plugins", "common", ...LAYOUT_NAMESPACES]);
  const communityPath = useCommunityPath();
  const { displays, columns: columnIds, card } = list.definition;
  const fields = useMemo(
    () => withDisplays(toolFields(table, i18n.language), displays),
    [table, i18n.language, displays]
  );
  const steps = usePluginToolSteps();
  const env = useMemo<LayoutEnv<ToolRow>>(() => {
    const envOf = (of: ToolTable): LayoutEnv<ToolRow> => ({
      t: t as TranslateFn,
      communityPath,
      itemHref: (row) => communityPath(toolPluginRowRoute(initiativeId, of.kind, row.id)),
      ...(editing ? {} : { stepCounter: steps(of) }),
    });
    // Each item table under it by its key, as a card's `items` part names it.
    const previews = new Map(
      table.items.flatMap((kind) => {
        const items = tool.tables.get(kind);
        if (!items) return [];
        const fields = withDisplays(
          toolFields(items, i18n.language),
          items.layouts.lists[0]?.displays
        );
        return [[kind.split(".")[0], { kind, fields, env: envOf(items) }] as const];
      })
    );
    return {
      ...envOf(table),
      itemPreview: (row, key): ItemPreview | null => {
        const preview = previews.get(key);
        const items = preview && row.preview?.[preview.kind];
        return items
          ? {
              items,
              fields: preview.fields as ItemPreview["fields"],
              env: preview.env as LayoutEnv,
            }
          : null;
      },
    };
  }, [t, communityPath, initiativeId, tool, table, editing, steps, i18n.language]);
  const sorted = useMemo(
    () => sortedItems(rows, sorting, fields, i18n.language) as R[],
    [rows, sorting, fields, i18n.language]
  );
  const columns = useMemo(
    () =>
      list.kind === "table"
        ? (columnIds ?? ["name"]).flatMap((id) => {
            const field = fields.get(id);
            return field ? [fieldColumn(field, env, { sortFn: "alphanumeric" })] : [];
          })
        : [],
    [list.kind, columnIds, fields, env]
  );
  const node = (card as LayoutNode | null | undefined) ?? NAME_CARD;
  const view = useMemo<LayoutContext<ToolRow>>(
    () => ({ fields, variant: "card", env, editing: editing ? indexPaths(node) : undefined }),
    [fields, env, editing, node]
  );

  if (list.kind === "table") {
    return (
      <DataTable
        columns={columns}
        data={sorted}
        getRowId={(row) => String(row.id)}
        manualSorting
        sorting={sorting}
        onSortingChange={onSortingChange}
      />
    );
  }
  const cardOf = (row: R) => (
    <Card className="h-full">
      <CardContent className="space-y-2 p-4">
        <LayoutTree node={node} item={row} view={view} />
      </CardContent>
    </Card>
  );
  const drawn = (row: R) =>
    selection ? (
      <SelectableGridItem
        active={selection.active}
        selected={selection.selectedIds.has(row.id)}
        onToggle={(options) => selection.toggle(row, options)}
        label={row.name}
      >
        {cardOf(row)}
      </SelectableGridItem>
    ) : (
      cardOf(row)
    );
  // A wall lets each card stand as tall as it is; a grid lines them up, each
  // as wide as a built-in tool's card.
  return list.kind === "masonry" ? (
    <ul className="columns-2xs gap-3">
      {sorted.map((row) => (
        <li key={row.id} className="mb-3 break-inside-avoid">
          {drawn(row)}
        </li>
      ))}
    </ul>
  ) : (
    <ul className="grid grid-cols-fill-60/3 gap-3">
      {sorted.map((row) => (
        <li key={row.id}>{drawn(row)}</li>
      ))}
    </ul>
  );
};
