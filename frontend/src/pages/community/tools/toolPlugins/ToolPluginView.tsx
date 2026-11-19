import { useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { usePluginToolRows } from "@/hooks/usePluginToolRows";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  type InstalledTool,
  type ToolTable,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { Button } from "@/ui/button";
import { CardGridSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { AddToolRowDialog } from "./AddToolRowDialog";
import { ToolRows } from "./ToolRows";

/**
 * The rows of one of a tool plug-in's tables in one place, as its list layout
 * draws them, and adding one: the tool's own in its initiative tab, or an item
 * table's on the page of the row they sit under.
 */
export const ToolTableRows = ({
  table,
  initiativeId,
  parentId,
  canCreate,
  primary = false,
}: {
  table: ToolTable;
  initiativeId: number;
  /** The row the items sit under; none for the tool's own rows. */
  parentId?: number;
  canCreate: boolean;
  /** Its adding is the page's own: the app's add button and `?create=true`. */
  primary?: boolean;
}) => {
  const { t, i18n } = useTranslation("plugins");
  const gp = useCommunityPath();
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

  return (
    <div className="space-y-4">
      {canCreate ? (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" />
            {label}
          </Button>
        </div>
      ) : null}
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
        <ToolRows
          table={table}
          list={table.layouts.list}
          rows={rows.data.items.map(toolRow)}
          initiativeId={initiativeId}
        />
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
