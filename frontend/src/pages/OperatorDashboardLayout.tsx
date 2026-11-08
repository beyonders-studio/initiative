import { Navigate, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import {
  Capability,
  canAccessOperatorDashboard,
  canManagePlatformConfig,
  hasCapability,
} from "@/lib/permissions";
import { matchActiveTab } from "@/lib/tabs";
import { SettingsPaneSkeleton } from "@/ui/page-skeletons";

/**
 * Operator dashboard: platform users and time-bound access grants.
 * Reachable by support/moderator/operator/owner depending on capability.
 * App-wide *configuration* lives in the separate Platform settings area.
 */
export const OperatorDashboardLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const { billing } = useAppConfig();
  const pathname = useLocation({ select: (location) => location.pathname });
  const router = useRouter();

  const tabs = useMemo(() => {
    // Each tab is visible if the user holds ANY of its capabilities.
    const all: { value: string; label: string; path: string; capabilities: Capability[] }[] = [
      {
        value: "users",
        label: t("operatorDashboard.tabs.users"),
        path: "/settings/operator/users",
        capabilities: [Capability.usersRead],
      },
      {
        value: "communities",
        label: t("operatorDashboard.tabs.communities"),
        path: "/settings/operator/communities",
        capabilities: [Capability.communitiesRead],
      },
      {
        value: "placement",
        label: t("operatorDashboard.tabs.placement"),
        path: "/settings/operator/placement",
        capabilities: [Capability.communitiesManage],
      },
      {
        value: "announcements",
        label: t("operatorDashboard.tabs.announcements"),
        path: "/settings/operator/announcements",
        capabilities: [Capability.announcementsManage],
      },
      // Only on a server connected to a billing service that can open it.
      ...(billing?.insights || billing?.contracts || billing?.directory || billing?.control
        ? [
            {
              value: "billing",
              label: t("operatorDashboard.tabs.billing"),
              path: "/settings/operator/billing",
              capabilities: [
                Capability.billingInsights,
                Capability.billingContracts,
                Capability.billingDirectory,
                Capability.billingControl,
              ],
            },
          ]
        : []),
      {
        value: "access",
        label: t("operatorDashboard.tabs.access"),
        path: "/settings/operator/access",
        capabilities: [Capability.accessRequest, Capability.accessApprove],
      },
    ];
    return all.filter((tab) => tab.capabilities.some((c) => hasCapability(user, c)));
  }, [t, user, billing?.insights, billing?.contracts, billing?.directory, billing?.control]);

  if (!canAccessOperatorDashboard(user)) {
    return <Navigate to={canManagePlatformConfig(user) ? "/settings/platform" : "/"} replace />;
  }

  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(tabs, normalizedPath, tabs[0]?.value ?? "users");

  return (
    <div className="space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("operatorDashboard.title")}</h1>
      <SettingsTabsNav
        tabs={tabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      />
      <Suspense fallback={<SettingsPaneSkeleton />}>
        <Outlet />
      </Suspense>
    </div>
  );
};
