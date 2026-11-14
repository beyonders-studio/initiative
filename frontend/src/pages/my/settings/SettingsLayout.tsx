import { Link, Outlet } from "@tanstack/react-router";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import { SettingsPageHeader } from "@/components/settings/SettingsPageHeader";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { VersionDialog } from "@/components/updates/VersionDialog";
import { useAuth } from "@/hooks/useAuth";
import { compareVersions, useLatestVersion } from "@/hooks/useLatestVersion";
import { usePrivacySections } from "@/hooks/usePrivacySections";
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

export const SettingsLayout = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const { data: latestVersion, isLoading: isLoadingVersion } = useLatestVersion();
  const currentVersion = __APP_VERSION__;
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

  const tabs = userSettingsTabs.map((tab) => ({
    value: tab.value,
    label: t(tab.labelKey),
    path: tab.path,
    visible: tab.value !== "privacy" || privacy.any,
  }));

  return (
    <div className="space-y-6">
      <SettingsPageHeader title={t("layout.title")} />
      <SettingsTabsNav tabs={tabs}>
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </SettingsTabsNav>
      {/* Which version this is, and what has changed lately: there for
          whoever wants it, and nowhere anyone passes on the way to something
          else. Updating is the Update button's, not this. */}
      <div className="flex items-center gap-3 text-muted-foreground text-xs">
        <span>{t("layout.version", { version: currentVersion })}</span>
        <VersionDialog
          currentVersion={currentVersion}
          latestVersion={latestVersion}
          hasUpdate={Boolean(latestVersion && compareVersions(latestVersion, currentVersion) > 0)}
          isLoadingVersion={isLoadingVersion}
        >
          <button
            type="button"
            className="cursor-pointer underline-offset-4 hover:text-foreground hover:underline"
          >
            {t("common:appUpdate.whatsNew")}
          </button>
        </VersionDialog>
      </div>
    </div>
  );
};
