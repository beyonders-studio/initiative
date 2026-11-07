import { Link, Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { useAuth } from "@/hooks/useAuth";
import { usePrivacySections } from "@/hooks/usePrivacySections";
import { matchActiveTab } from "@/lib/tabs";
import { Button } from "@/ui/button";
import { SettingsPaneSkeleton } from "@/ui/page-skeletons";

const userSettingsTabs = [
  { value: "profile", labelKey: "layout.tabs.profile", path: "/profile" },
  { value: "account", labelKey: "layout.tabs.account", path: "/profile/account" },
  { value: "interface", labelKey: "layout.tabs.interface", path: "/profile/interface" },
  { value: "notifications", labelKey: "layout.tabs.notifications", path: "/profile/notifications" },
  { value: "privacy", labelKey: "layout.tabs.privacy", path: "/profile/privacy" },
  { value: "security", labelKey: "layout.tabs.security", path: "/profile/security" },
  { value: "trash", labelKey: "layout.tabs.trash", path: "/profile/trash" },
] as const;

export const UserSettingsLayout = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const pathname = useLocation({ select: (location) => location.pathname });
  const router = useRouter();
  // Privacy is offered while any of its sections has something to set here.
  const privacy = usePrivacySections();

  if (!user) {
    return (
      <div className="space-y-6">
        <p className="text-destructive">{t("layout.loginRequired")}</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/login">{t("layout.goToLogin")}</Link>
        </Button>
      </div>
    );
  }

  const tabs = userSettingsTabs
    .filter((tab) => tab.value !== "privacy" || privacy.any)
    .map((tab) => ({
      value: tab.value,
      label: t(tab.labelKey),
      path: tab.path,
    }));
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const activeTab = matchActiveTab(tabs, normalizedPath, "registration");

  return (
    <div className="space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("layout.title")}</h1>
      <SettingsTabsNav
        tabs={tabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      >
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </SettingsTabsNav>
    </div>
  );
};
