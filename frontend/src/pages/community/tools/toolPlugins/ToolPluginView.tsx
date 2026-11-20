import { useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { ToolListToolbar } from "@/components/tools/ToolListToolbar";
import { ToolPresetSelect } from "@/components/tools/ToolPresetSelect";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { layoutViewSpec, useListView, viewKey } from "@/hooks/useListView";
import { usePluginToolRows } from "@/hooks/usePluginToolRows";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type InstalledTool,
  type ToolTable,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import type { TranslateFn } from "@/types/i18n";
import { Button } from "@/ui/button";
import { shippedLists } from "@/ui/layouts/layoutSet";
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
 * table's on the page of the row they sit under.
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
  const { t, i18n } = useTranslation(["plugins", "layouts", "projects"]);
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();
  const navigate = useNavigate();
  const rows = usePluginToolRows(
    table.kind,
    parentId === undefined ? { initiative_id: initiativeId } : { parent_id: parentId }
  );
  // The page's own rows open their dialog from the URL; an item table's opens
  // its own.
  const fromSearch = useCreateFromSearchParam();
  const [adding, setAdding] = useState(false);
  const open = primary ? fromSearch.open : adding;
  const setOpen = primary ? fromSearch.setOpen : setAdding;
  const onOpenChange = primary ? fromSearch.onOpenChange : setAdding;
  const label = t("tool.create", { name: toolText(table.name, i18n.language) });
  useRegisterPrimaryCreateAction(primary && canCreate ? { run: () => setOpen(true), label } : null);

  // The lists it declares, drawn as shipped, and the one this person was last
  // in here, or the first.
  const lists = useMemo(() => shippedLists(table.layouts.lists), [table.layouts.lists]);
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
  const list = lists.find((each) => each.kind === listView.layout) ?? lists[0];
  // Its presets sort it as a view: the rows keep their own order.
  const presets = useMemo(
    () => presetsOf(list?.definition, { shipped: [], read: () => null, sorting: fieldSorting }),
    [list]
  );
  const activePreset =
    presets.find((preset) => JSON.stringify(preset.sorting) === JSON.stringify(listView.sorting)) ??
    null;

  const add = canCreate ? (
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
          presets.length > 0 ? (
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
          ) : undefined
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
          {t("tool.empty")}
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
