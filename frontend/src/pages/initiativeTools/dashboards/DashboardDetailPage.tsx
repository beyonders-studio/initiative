import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DashboardViewMode, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { DashboardUpdateBadge } from "@/components/initiativeTools/dashboards/DashboardUpdateBadge";
import { InitiativeViewNotice } from "@/components/initiativeTools/dashboards/InitiativeViewNotice";
import { WidgetConfigDialog } from "@/components/initiativeTools/dashboards/WidgetConfigDialog";
import { WidgetPicker } from "@/components/initiativeTools/dashboards/WidgetPicker";
import { DetailHeaderSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useDashboardEditor } from "@/hooks/useDashboardEditor";
import { useDashboard, useUpdateDashboard, useWidgetCatalog } from "@/hooks/useDashboards";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

export function DashboardDetailPage() {
  const { t } = useTranslation(["dashboards", "common"]);
  const { dashboardId } = useParams({ strict: false }) as { dashboardId: string };
  const parsedId = Number(dashboardId);
  const gp = useCommunityPath();

  const dashboardQuery = useDashboard(Number.isFinite(parsedId) ? parsedId : null);
  const dashboard = dashboardQuery.data;
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(dashboard?.initiative_id);

  // Track recently viewed dashboards for the layout header tabs bar — only
  // once the read succeeds (access checks passed).
  const viewedDashboardId = dashboard?.id;
  useReadOnOpen(Tool.dashboard, viewedDashboardId);
  useRecordOpen(Tool.dashboard, viewedDashboardId);

  const catalogQuery = useWidgetCatalog();
  // Arranging and binding are authoring — they write the dashboard's own row —
  // so the canvas is static without DAC write rather than merely looking it.
  const canEdit = Boolean(dashboard?.can.edit);
  const editor = useDashboardEditor(dashboard, catalogQuery.data, canEdit);
  const rename = useUpdateDashboard(parsedId);
  const [configuringId, setConfiguringId] = useState<string | null>(null);
  const configuring =
    editor.definition.widgets.find((widget) => widget.id === configuringId) ?? null;

  if (!Number.isFinite(parsedId) || dashboardQuery.isError) {
    return (
      <ToolAccessStatus
        error={dashboardQuery.error}
        keys="dashboards:"
        backTo={gp(toolListRoute(Tool.dashboard, initiativeId))}
        backLabel={t("backToDashboards")}
        entity={{ kind: "dashboard", id: parsedId }}
      />
    );
  }

  // The page frame is correct as soon as the route resolves; only the canvas is
  // waiting on anything. Replacing the whole page with a spinner would throw the
  // breadcrumb, title, and toolbar away and rebuild them a moment later, which
  // is what made an ordinary load look like a reload.
  return (
    <div className="space-y-6">
      {dashboard ? (
        <ToolPageHeader
          tool={Tool.dashboard}
          initiativeId={dashboard.initiative_id}
          starId={dashboard.id}
          settingsTo={
            canEdit ? toolSettingsRoute(Tool.dashboard, initiativeId, dashboard.id) : undefined
          }
          chest={
            <ToolChest tool={Tool.dashboard} entity={dashboard}>
              <ToolChestSegment>
                <div className="flex items-center gap-2">
                  <DashboardUpdateBadge dashboard={dashboard} canEdit={canEdit} />
                  {canEdit && (
                    <>
                      <WidgetPicker
                        catalog={catalogQuery.data}
                        widgetCount={editor.definition.widgets.length}
                        onAdd={editor.addWidget}
                      />
                      {editor.isSaving && (
                        <span className="text-muted-foreground text-xs">{t("canvas.saving")}</span>
                      )}
                    </>
                  )}
                </div>
              </ToolChestSegment>
            </ToolChest>
          }
          title={dashboard.name}
          onRename={canEdit ? (name) => rename.mutateAsync({ name }) : undefined}
        >
          {dashboard.description && (
            <p className="text-muted-foreground text-sm">{dashboard.description}</p>
          )}
          {dashboard.view_mode === DashboardViewMode.initiative && <InitiativeViewNotice />}
        </ToolPageHeader>
      ) : (
        <DetailHeaderSkeleton actions={0} description={false} />
      )}

      <DashboardCanvas
        definition={editor.definition}
        config={editor.config}
        catalog={catalogQuery.data}
        initiativeId={dashboard?.initiative_id}
        dashboardId={dashboard?.id}
        canEdit={canEdit}
        isLoading={!dashboard}
        onLayoutChange={editor.replaceDefinition}
        onConfigureWidget={setConfiguringId}
        onRemoveWidget={editor.removeWidget}
      />

      <ToolRelationsPanel
        tool={Tool.dashboard}
        entity={dashboard}
        canEdit={canEdit}
        entityTitle={dashboard?.name}
      />

      {dashboard != null && <ToolCommentsPanel tool={Tool.dashboard} entity={dashboard} />}

      {dashboard != null && (
        <WidgetConfigDialog
          widget={configuring}
          catalog={catalogQuery.data}
          initiativeId={dashboard.initiative_id}
          dashboardId={dashboard.id}
          open={configuring !== null}
          onOpenChange={(next) => !next && setConfiguringId(null)}
          onSave={(patch) => configuringId && editor.updateWidget(configuringId, patch)}
        />
      )}
    </div>
  );
}
