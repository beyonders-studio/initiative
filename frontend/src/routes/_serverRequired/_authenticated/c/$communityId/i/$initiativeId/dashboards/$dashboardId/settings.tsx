import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useDashboard } from "@/hooks/useDashboards";
import { useRouteId } from "@/hooks/useRouteId";
import { DashboardViewModeField } from "@/pages/community/tools/dashboards/DashboardViewModeField";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/settings"
)({
  component: DashboardSettings,
});

function DashboardSettings() {
  const dashboard = useDashboard(useRouteId("dashboardId")).data;
  return (
    <SettingsLayout
      tool={Tool.dashboard}
      detailsInline={dashboard && <DashboardViewModeField dashboard={dashboard} />}
    />
  );
}
