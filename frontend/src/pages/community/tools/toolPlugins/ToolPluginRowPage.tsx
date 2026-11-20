import { useParams } from "@tanstack/react-router";
import { SearchX } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { itemSaves } from "@/hooks/useFieldSave";
import { pluginToolRowSaves, useInstalledTools, usePluginToolRow } from "@/hooks/usePluginToolRows";
import { useRouteId } from "@/hooks/useRouteId";
import { useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  toolLayoutTarget,
  toolOfKind,
  toolPluginListRoute,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import type { StoredRegions } from "@/ui/layouts/detailLayout";
import { detailLayoutOf } from "@/ui/layouts/layoutSet";
import { Section } from "@/ui/layouts/section";
import { DetailPageSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { RowActions } from "./RowActions";
import { ToolTableRows } from "./ToolPluginView";
import { toolDetail } from "./toolDetail";

/**
 * One row of a tool plug-in, the tool's own or an item's, on its own page: its
 * table's detail layout, then the rows of each item table under it, each as
 * that table's list layout draws them.
 */
export function ToolPluginRowPage() {
  const { t, i18n } = useTranslation("plugins");
  const gp = useCommunityPath();
  const { kind = "" } = useParams({ strict: false }) as { kind?: string };
  const rowId = useRouteId("rowId");
  const initiativeId = useRouteId("initiativeId");
  const installs = useInstalledTools();
  const found = installs.status === "ready" ? toolOfKind(installs.tools, kind) : null;
  const query = usePluginToolRow(kind, found ? rowId : null);
  const row = useMemo(() => (query.data ? toolRow(query.data) : null), [query.data]);
  const table = found?.table;
  const detail = useMemo(
    () => (table ? toolDetail(table, i18n.language) : null),
    [table, i18n.language]
  );
  const saves = useMemo(() => itemSaves(pluginToolRowSaves(kind), rowId ?? 0), [kind, rowId]);
  // Its page as the place it is listed in laid it out, or as shipped.
  const layouts = useToolLayouts(
    table && row ? toolLayoutTarget(table, row.initiative_id, row.parent_id) : null
  );

  if (installs.status === "loading" || query.isLoading) {
    return (
      <SkeletonRegion>
        <DetailPageSkeleton />
      </SkeletonRegion>
    );
  }
  if (installs.status === "error") {
    return <StatusMessage title={t("tool.installsLoadError")} onRetry={installs.retry} />;
  }
  if (!found || !table || !detail || !row || initiativeId === null) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("tool.notFound")}
        description={t("tool.notFoundBody")}
        backTo={initiativeId === null ? gp("/") : gp(`/i/${initiativeId}`)}
        backLabel={t("tool.backToTool", {
          name: found ? toolText(found.tool.name, i18n.language) : "",
        })}
      />
    );
  }

  const { tool } = found;
  // The row it is an item of, which its crumb leads back to.
  const parent =
    row.parent_id !== null && table.parent
      ? {
          label: toolText(tool.tables.get(table.parent)?.name ?? {}, i18n.language),
          to: toolPluginRowRoute(row.initiative_id, table.parent, row.parent_id),
        }
      : null;
  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={{
          label: toolText(tool.name, i18n.language),
          to: toolPluginListRoute(row.initiative_id, tool.kind),
        }}
        initiativeId={row.initiative_id}
        trail={parent ? [parent] : []}
      />
      <DetailLayoutView
        detail={detail}
        item={row}
        layout={detailLayoutOf(layouts.data, table.kind) as StoredRegions | null}
        context={{
          readOnly: !row.can.edit,
          initiativeId: row.initiative_id,
          saves,
          actions: <RowActions table={table} row={row} language={i18n.language} />,
        }}
      />
      {table.items.map((itemKind) => {
        const items = tool.tables.get(itemKind);
        return items ? (
          <Section key={itemKind} title={toolText(items.name, i18n.language)}>
            <ToolTableRows
              table={items}
              initiativeId={row.initiative_id}
              parentId={row.id}
              canCreate={row.can.contribute}
            />
          </Section>
        ) : null;
      })}
    </div>
  );
}
