import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { DashboardViewModeField } from "@/components/initiativeTools/dashboards/DashboardViewModeField";
import { useDashboard } from "@/hooks/useDashboards";
import { useRouteId } from "@/hooks/useRouteId";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/settings"
)({
  component: DashboardSettings,
});

function DashboardSettings() {
  const dashboard = useDashboard(useRouteId("dashboardId")).data;
  return (
    <ToolSettingsPage
      tool={Tool.dashboard}
      detailsInline={dashboard && <DashboardViewModeField dashboard={dashboard} />}
    />
  );
}
