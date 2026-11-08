import { Navigate, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
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
 * App-wide *configuration* area: authentication, security, branding, email,
 * push notifications, integrations (AI and plug-in service registrations), and
 * storage. Owner-only (`config.manage` / `plugins.manage`).
 * Operational tools (users, access) live in the separate Operator dashboard.
 */
export const PlatformSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const pathname = useLocation({ select: (location) => location.pathname });
  const router = useRouter();

  const tabs = useMemo(() => {
    // Two capabilities reach this area: `config.manage` owns app-wide
    // configuration, `plugins.manage` owns plug-in service registrations. A holder of
    // one shouldn't be shown the other's tabs — and Integrations, which holds
    // both the AI settings and the plug-in service registrations, is shown to
    // either.
    const canManageConfig = hasCapability(user, Capability.configManage);
    const canManagePlugins = hasCapability(user, Capability.pluginsManage);
    return [
      {
        value: "auth",
        label: t("platformLayout.tabs.auth"),
        path: "/settings/platform/auth",
        visible: canManageConfig,
      },
      {
        value: "security",
        label: t("platformLayout.tabs.security"),
        path: "/settings/platform/security",
        visible: canManageConfig,
      },
      {
        value: "branding",
        label: t("platformLayout.tabs.branding"),
        path: "/settings/platform/branding",
        visible: canManageConfig,
      },
      {
        value: "email",
        label: t("platformLayout.tabs.email"),
        path: "/settings/platform/email",
        visible: canManageConfig,
      },
      {
        value: "push",
        label: t("platformLayout.tabs.push"),
        path: "/settings/platform/push",
        visible: canManageConfig,
      },
      {
        value: "community",
        label: t("platformLayout.tabs.community"),
        path: "/settings/platform/community",
        visible: canManageConfig,
      },
      {
        value: "integrations",
        label: t("platformLayout.tabs.integrations"),
        path: "/settings/platform/integrations",
        visible: canManageConfig || canManagePlugins,
      },
      {
        value: "storage",
        label: t("platformLayout.tabs.storage"),
        path: "/settings/platform/storage",
        visible: canManageConfig,
      },
      {
        value: "intake",
        label: t("platformLayout.tabs.intake"),
        path: "/settings/platform/intake",
        visible: canManageConfig,
      },
    ]
      .filter((tab) => tab.visible)
      .map(({ visible: _visible, ...tab }) => tab);
  }, [t, user]);

  if (!canManagePlatformConfig(user)) {
    // Send operational staff to their dashboard; everyone else back to the app.
    return <Navigate to={canAccessOperatorDashboard(user) ? "/settings/operator" : "/"} replace />;
  }

  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  // Fall back to whichever tab this user actually has, not always `auth`.
  const activeTab = matchActiveTab(tabs, normalizedPath, tabs[0]?.value ?? "auth");

  return (
    <div className="space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("platformLayout.title")}</h1>
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
