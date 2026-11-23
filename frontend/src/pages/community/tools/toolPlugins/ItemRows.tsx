import { useNavigate } from "@tanstack/react-router";
import { FileText, LayoutList as LayoutsIcon, Plus } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ToolListToolbar } from "@/components/tools/ToolListToolbar";
import { ToolPresetSelect } from "@/components/tools/ToolPresetSelect";
import { ToolViewFilter } from "@/components/tools/ToolViewFilter";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { layoutViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { usePluginToolRows } from "@/hooks/usePluginToolRows";
import { useSaveLayouts, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type InstalledTool,
  type ToolTable,
  toolLayoutTarget,
  toolPluginLayoutsRoute,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { type ToolView, toolViewParams } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import { sameJson } from "@/ui/layouts/editing";
import { LayoutsDialog } from "@/ui/layouts/LayoutList";
import { laidOutLists, shippedLists } from "@/ui/layouts/layoutSet";
import { listLayoutLooks } from "@/ui/layouts/looks";
import { fieldSorting, presetName, presetsOf } from "@/ui/layouts/presets";
import { CardGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { AddToolRowDialog } from "./AddToolRowDialog";
import { ToolRows } from "./ToolRows";

type ListView = ReturnType<typeof useListView>;

/**
 * The lists a tool plug-in's table declares where its rows are listed, each
 * as that place laid it out or as shipped, and the one this person picked in
 * `listView`; its presets, which sort it; and the dialog its layouts are
 * changed from. The tool's own rows' page (`ToolIndexPage`) and an item
 * table's rows under a row both list through it; with no table, a built-in
 * tool's page, it lists nothing.
 */
export const useToolLists = (
  table: ToolTable | null,
  initiativeId: number,
  parentId: number | null,
  listView: Pick<ListView, "layout" | "rememberLayout" | "sorting" | "setSorting">
) => {
  const { t, i18n } = useTranslation(["plugins", "layouts", "projects"]);
  const gp = useCommunityPath();
  const kind = table?.kind;
  const target = useMemo(
    () => (kind ? toolLayoutTarget(kind, initiativeId, parentId) : null),
    [kind, initiativeId, parentId]
  );
  const layouts = useToolLayouts(target);
  const save = useSaveLayouts(target ?? { tool: "" });
  const [open, setOpen] = useState(false);
  const declared = table?.layouts.lists;
  const lists = useMemo(
    () =>
      declared
        ? laidOutLists(shippedLists(declared), layouts.data).filter((each) => !each.hidden)
        : [],
    [declared, layouts.data]
  );
  const list =
    lists.find((each) => each.kind === listView.layout) ??
    lists.find((each) => each.is_default) ??
    lists[0];
  // Its presets sort it as a view: the rows keep their own order.
  const presets = useMemo(
    () => presetsOf(list?.definition, { shipped: [], read: () => null, sorting: fieldSorting }),
    [list]
  );
  const active = presets.find((preset) => sameJson(preset.sorting, listView.sorting)) ?? null;
  const configurable = table && layouts.data?.can_configure ? layouts.data : null;
  return {
    list,
    view:
      lists.length > 1 && list
        ? {
            value: list.kind,
            onChange: listView.rememberLayout,
            label: t("layouts:views"),
            options: lists.map((each) => ({
              value: each.kind,
              label: t(listLayoutLooks[each.kind].labelKey as never),
              icon: listLayoutLooks[each.kind].icon,
            })),
          }
        : undefined,
    presetSelect:
      presets.length > 0 ? (
        <ToolPresetSelect
          presets={presets.map((preset) => ({
            slug: preset.slug,
            name: presetName(preset, t as TranslateFn, i18n.language),
          }))}
          activeSlug={active?.slug ?? null}
          onSelect={(slug) => {
            const picked = presets.find((preset) => preset.slug === slug);
            if (picked) listView.setSorting(picked.sorting);
          }}
          label={t("projects:presets.label")}
          placeholder={t("projects:presets.placeholder")}
        />
      ) : null,
    menuItem: configurable ? (
      <DropdownMenuItem onSelect={() => setOpen(true)}>
        <LayoutsIcon className="h-4 w-4" />
        {t("layouts:tab")}
      </DropdownMenuItem>
    ) : undefined,
    dialog:
      table && configurable ? (
        <LayoutsDialog
          open={open}
          onOpenChange={setOpen}
          layouts={configurable.layouts}
          pageLooks={{
            [table.kind]: {
              icon: FileText,
              labelKey: "",
              label: t("tool.layout.name", { name: toolText(table.name, i18n.language) }),
            },
          }}
          save={save.mutateAsync}
          editor={gp(toolPluginLayoutsRoute(initiativeId, table.kind, parentId))}
        />
      ) : null,
  };
};

/**
 * The rows of an item table under one row, on that row's page: every one of
 * them, in the list this person picked of those it declares, sorted by the
 * preset they picked, and adding one. Its archived rows are a view of their
 * own, as every tool's are.
 */
export const ItemRows = ({
  tool,
  table,
  initiativeId,
  parentId,
  canCreate,
  heading,
}: {
  tool: InstalledTool;
  table: ToolTable;
  initiativeId: number;
  parentId: number;
  canCreate: boolean;
  /** What its control row is headed with. */
  heading?: ReactNode;
}) => {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const navigate = useNavigate();
  const [view, setView] = useState<ToolView>("active");
  const rows = usePluginToolRows(table, {
    parent_id: parentId,
    ...toolViewParams(table.kind, view),
  });
  const [adding, setAdding] = useState(false);
  // Nothing is made into the archive.
  const canAdd = canCreate && view !== "archived";
  const listView = useListView(
    useMemo(
      () => layoutViewSpec(communityId, viewKey("tool", table.kind, parentId), () => undefined),
      [communityId, table.kind, parentId]
    )
  );
  const lists = useToolLists(table, initiativeId, parentId, listView);

  return (
    <div className="space-y-4">
      <ToolListToolbar
        heading={heading}
        leading={
          <div className="flex items-center gap-2">
            <ToolViewFilter tool={table.kind} value={view} onChange={setView} />
            {lists.presetSelect}
          </div>
        }
        view={lists.view}
        menuItems={lists.menuItem}
        trailing={
          canAdd ? (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" />
              {t("tool.create", { name: toolText(table.name, i18n.language) })}
            </Button>
          ) : null
        }
      />
      {rows.isLoading ? (
        <SkeletonRegion>
          <CardGridSkeleton count={3} />
        </SkeletonRegion>
      ) : rows.isError || !rows.data ? (
        <StatusMessage title={t("tool.loadError")} onRetry={() => void rows.refetch()} />
      ) : rows.data.items.length === 0 ? (
        <p className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
          {view === "archived" ? t("common:toolIndex.emptyArchivedBody") : t("tool.empty")}
        </p>
      ) : (
        lists.list && (
          <ToolRows
            tool={tool}
            table={table}
            list={lists.list}
            rows={rows.data.items.map(toolRow)}
            initiativeId={initiativeId}
            sorting={listView.sorting}
            onSortingChange={listView.setSorting}
          />
        )
      )}
      {lists.dialog}
      {canCreate ? (
        <AddToolRowDialog
          open={adding}
          onOpenChange={setAdding}
          table={table}
          initiativeId={initiativeId}
          parentId={parentId}
          onAdded={(made) => {
            setAdding(false);
            void navigate({ to: gp(toolPluginRowRoute(initiativeId, table.kind, made.id)) });
          }}
        />
      ) : null}
    </div>
  );
};
