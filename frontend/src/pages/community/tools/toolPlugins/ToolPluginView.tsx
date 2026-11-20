import { useNavigate } from "@tanstack/react-router";
import { FileText, LayoutList as LayoutsIcon, Plus } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { ToolListToolbar } from "@/components/tools/ToolListToolbar";
import { ToolPresetSelect } from "@/components/tools/ToolPresetSelect";
import { ToolViewFilter } from "@/components/tools/ToolViewFilter";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
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
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import { LayoutsOverview } from "@/ui/layouts/LayoutList";
import { laidOutLists, shippedLists } from "@/ui/layouts/layoutSet";
import { listLayoutLooks } from "@/ui/layouts/looks";
import { fieldSorting, presetName, presetsOf } from "@/ui/layouts/presets";
import { CardGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { AddToolRowDialog } from "./AddToolRowDialog";
import { ToolRows } from "./ToolRows";

/**
 * The rows of one of a tool plug-in's tables in one place, in the list this
 * person picked of those it declares and sorted by the preset they picked, as
 * a built-in tool's list is, and adding one: the tool's own in its initiative tab, or an item
 * table's on the page of the row they sit under. Its archived rows are a view
 * of their own, as every tool's are.
 */
export const ToolTableRows = ({
  table,
  initiativeId,
  parentId,
  canCreate,
  primary = false,
  heading,
}: {
  table: ToolTable;
  initiativeId: number;
  /** The row the items sit under; none for the tool's own rows. */
  parentId?: number;
  canCreate: boolean;
  /** Its adding is the page's own: the app's add button and `?create=true`. */
  primary?: boolean;
  /** What its control row is headed with: an item table's name. */
  heading?: ReactNode;
}) => {
  const { t, i18n } = useTranslation(["plugins", "layouts", "projects", "common"]);
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const navigate = useNavigate();
  const [view, setView] = useState<ToolView>("active");
  const rows = usePluginToolRows(table.kind, {
    ...(parentId === undefined ? { initiative_id: initiativeId } : { parent_id: parentId }),
    ...toolViewParams(table.kind, view),
  });
  // Nothing is made into the archive.
  const canAdd = canCreate && view !== "archived";
  // The page's own rows open their dialog from the URL; an item table's opens
  // its own.
  const fromSearch = useCreateFromSearchParam();
  const [adding, setAdding] = useState(false);
  const open = primary ? fromSearch.open : adding;
  const setOpen = primary ? fromSearch.setOpen : setAdding;
  const onOpenChange = primary ? fromSearch.onOpenChange : setAdding;
  const label = t("tool.create", { name: toolText(table.name, i18n.language) });
  useRegisterPrimaryCreateAction(primary && canAdd ? { run: () => setOpen(true), label } : null);

  // The lists it declares, each as this place laid it out or as shipped, and
  // the one this person was last in here, or the one it opens on.
  const target = useMemo(
    () => toolLayoutTarget(table, initiativeId, parentId ?? null),
    [table, initiativeId, parentId]
  );
  const layouts = useToolLayouts(target);
  const saveLayouts = useSaveLayouts(target);
  const [layoutsOpen, setLayoutsOpen] = useState(false);
  const lists = useMemo(
    () =>
      laidOutLists(shippedLists(table.layouts.lists), layouts.data).filter((each) => !each.hidden),
    [table.layouts.lists, layouts.data]
  );
  const listView = useListView(
    useMemo(
      () =>
        layoutViewSpec(
          communityId,
          viewKey("tool", table.kind, parentId ?? `initiative-${initiativeId}`),
          () => undefined
        ),
      [communityId, table.kind, parentId, initiativeId]
    )
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
  const activePreset =
    presets.find((preset) => JSON.stringify(preset.sorting) === JSON.stringify(listView.sorting)) ??
    null;

  const add = canAdd ? (
    <Button size="sm" onClick={() => setOpen(true)}>
      <Plus className="h-4 w-4" />
      {label}
    </Button>
  ) : null;

  return (
    <div className="space-y-4">
      <ToolListToolbar
        heading={heading}
        leading={
          <div className="flex items-center gap-2">
            <ToolViewFilter tool={table.kind} value={view} onChange={setView} />
            {presets.length > 0 ? (
              <ToolPresetSelect
                presets={presets.map((preset) => ({
                  slug: preset.slug,
                  name: presetName(preset, t as TranslateFn, i18n.language),
                }))}
                activeSlug={activePreset?.slug ?? null}
                onSelect={(slug) => {
                  const picked = presets.find((preset) => preset.slug === slug);
                  if (picked) listView.setSorting(picked.sorting);
                }}
                label={t("projects:presets.label")}
                placeholder={t("projects:presets.placeholder")}
              />
            ) : null}
          </div>
        }
        view={
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
            : undefined
        }
        menuItems={
          layouts.data?.can_configure ? (
            <DropdownMenuItem onSelect={() => setLayoutsOpen(true)}>
              <LayoutsIcon className="h-4 w-4" />
              {t("layouts:tab")}
            </DropdownMenuItem>
          ) : undefined
        }
        // The page's own add is the app's add button on a phone too.
        {...(primary ? { actions: add } : { trailing: add })}
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
        list && (
          <ToolRows
            table={table}
            list={list}
            rows={rows.data.items.map(toolRow)}
            initiativeId={initiativeId}
            sorting={listView.sorting}
            onSortingChange={listView.setSorting}
          />
        )
      )}
      {layouts.data?.can_configure ? (
        <Dialog open={layoutsOpen} onOpenChange={setLayoutsOpen}>
          <DialogContent className="sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>{t("layouts:tab")}</DialogTitle>
              <DialogDescription>{t("layouts:settingsDescription")}</DialogDescription>
            </DialogHeader>
            <LayoutsOverview
              layouts={layouts.data.layouts}
              pageLooks={{
                [table.kind]: {
                  icon: FileText,
                  labelKey: "",
                  label: t("tool.layout.name", { name: toolText(table.name, i18n.language) }),
                },
              }}
              save={saveLayouts.mutateAsync}
              editor={gp(toolPluginLayoutsRoute(initiativeId, table.kind, parentId ?? null))}
            />
          </DialogContent>
        </Dialog>
      ) : null}
      {canCreate ? (
        <AddToolRowDialog
          open={open}
          onOpenChange={onOpenChange}
          table={table}
          initiativeId={initiativeId}
          parentId={parentId}
          onAdded={(made) => {
            onOpenChange(false);
            void navigate({ to: gp(toolPluginRowRoute(initiativeId, table.kind, made.id)) });
          }}
        />
      ) : null}
    </div>
  );
};

/** A tool plug-in's tab on its initiative's page: the tool's own rows. */
export const ToolPluginView = ({
  tool,
  fixedInitiativeId,
  canCreate,
}: {
  tool: InstalledTool;
  fixedInitiativeId: number;
  canCreate: boolean;
}) => {
  const table = tool.tables.get(tool.kind);
  return table ? (
    <ToolTableRows table={table} initiativeId={fixedInitiativeId} canCreate={canCreate} primary />
  ) : null;
};
