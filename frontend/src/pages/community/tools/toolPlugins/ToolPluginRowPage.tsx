import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { SearchX } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { itemSaves } from "@/hooks/useFieldSave";
import { pluginToolRowSaves, usePluginToolRow, usePluginToolRows } from "@/hooks/usePluginToolRows";
import { useRouteId } from "@/hooks/useRouteId";
import { useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  selectInstalledTools,
  toolLayoutTarget,
  toolOfKind,
  toolPluginListRoute,
  toolPluginRowRoute,
  toolRow,
  toolText,
} from "@/lib/toolPlugins";
import { toolViewParams } from "@/lib/tools";
import { DetailLayoutView } from "@/ui/layouts/DetailLayoutView";
import type { StoredRegions } from "@/ui/layouts/detailLayout";
import { detailLayoutOf } from "@/ui/layouts/layoutSet";
import { Section } from "@/ui/layouts/section";
import { DetailPageSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { ItemRows } from "./ItemRows";
import { RowActions } from "./RowActions";
import { type ToolRowContext, toolDetail } from "./toolDetail";

/**
 * One row of a tool plug-in, the tool's own or an item's, on its own page: its
 * table's detail layout, then the rows of each item table under it, each as
 * that table's list layout draws them.
 */
export function ToolPluginRowPage() {
  const { t, i18n } = useTranslation("plugins");
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const { kind = "" } = useParams({ strict: false }) as { kind?: string };
  const { focus: focused = null } = useSearch({ strict: false }) as { focus?: string };
  const rowId = useRouteId("rowId");
  const initiativeId = useRouteId("initiativeId");
  // The installs, the row and its page's layouts are read side by side: the
  // kind and the row are the URL's.
  const installs = useCommunityPlugins({ select: selectInstalledTools });
  const found = installs.data ? toolOfKind(installs.data, kind) : null;
  const query = usePluginToolRow(kind, rowId);
  const row = useMemo(() => (query.data ? toolRow(query.data) : null), [query.data]);
  const table = found?.table;
  const detail = useMemo(
    () => (table ? toolDetail(table, i18n.language) : null),
    [table, i18n.language]
  );
  const saves = useMemo(() => itemSaves(pluginToolRowSaves(kind), rowId ?? 0), [kind, rowId]);
  // Its page as the place it is listed in laid it out, or as shipped: the
  // tool's own rows' in the URL's initiative, an item's under its row.
  const parentId = row ? row.parent_id : table?.parent === null ? null : undefined;
  const layouts = useToolLayouts(
    parentId === undefined || initiativeId === null
      ? null
      : toolLayoutTarget(kind, initiativeId, parentId)
  );
  // The rows a counter full screen moves between, read once it is open: those
  // listed beside this one, in their own order.
  const siblings = usePluginToolRows(
    { kind, items: table?.items ?? [] },
    {
      ...(row?.parent_id ? { parent_id: row.parent_id } : { initiative_id: row?.initiative_id }),
      ...toolViewParams(kind, "active"),
    },
    { enabled: focused !== null && row !== null }
  );
  const focus = useMemo<ToolRowContext["focus"]>(() => {
    if (!row) return undefined;
    const rows = siblings.data?.items ?? [];
    const index = rows.findIndex((each) => each.id === row.id);
    const open = (field: string | null, id = row.id) =>
      void navigate({
        to: gp(toolPluginRowRoute(row.initiative_id, kind, id)),
        search: field === null ? {} : { focus: field },
        replace: true,
      });
    return (field) => ({
      open: focused === field,
      onOpenChange: (next) => open(next ? field : null),
      navigation:
        index < 0
          ? undefined
          : {
              index,
              total: rows.length,
              onMove: (by) => {
                const next = rows[(index + by + rows.length) % rows.length];
                if (next) open(field, next.id);
              },
            },
    });
  }, [row, siblings.data, focused, kind, gp, navigate]);

  if (installs.isLoading || query.isLoading) {
    return (
      <SkeletonRegion>
        <DetailPageSkeleton />
      </SkeletonRegion>
    );
  }
  // A refresh that fails keeps the installs it had.
  if (installs.isError && !installs.data) {
    return (
      <StatusMessage title={t("tool.installsLoadError")} onRetry={() => void installs.refetch()} />
    );
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
          focus,
        }}
      />
      {table.items.map((itemKind) => {
        const items = tool.tables.get(itemKind);
        return items ? (
          <Section key={itemKind} title={toolText(items.name, i18n.language)}>
            <ItemRows
              tool={tool}
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
