import { Outlet, useLocation, useRouter } from "@tanstack/react-router";
import { type ReactNode, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { SettingsPaneSkeleton } from "@/components/skeletons/PageSkeletons";
import { HelpLink } from "@/components/support/HelpLink";
import { Badge } from "@/components/ui/badge";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityBillingSummary } from "@/hooks/useCommunityBillingSummary";
import { useCommunitySettingsTabs } from "@/hooks/useCommunitySettingsTabs";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { trialDaysLeft } from "@/lib/billingSummary";
import { extractSubPath, isCommunityScopedPath } from "@/lib/communityUrl";
import { matchActiveTab } from "@/lib/tabs";

export const CommunitySettingsLayout = () => {
  const { t } = useTranslation(["settings"]);
  const { activeCommunity } = useCommunities();
  // Whether what the reader holds may also be changed. Without it every
  // control on these pages is shown disabled.
  const changesSettings = useHeldSurfaces().writes;
  const location = useLocation();
  const router = useRouter();
  const { tabs, isLoading } = useCommunitySettingsTabs();

  // The Usage tab says when the plan wants a look: a failed payment, or a
  // trial running out. Hosted only — the query never runs without a portal —
  // and the query the tab's own panel reads, so opening it is one request.
  const { data: summary } = useCommunityBillingSummary(activeCommunity);
  const communitySettingsTabs = useMemo(() => {
    let usageMark: ReactNode = null;
    const daysLeft = trialDaysLeft(summary);
    if (summary?.available && summary.payment_failed) {
      const label = t("communityLayout.tabBadge.paymentFailed");
      usageMark = (
        <span
          role="img"
          aria-label={label}
          title={label}
          className="h-2 w-2 rounded-full bg-destructive"
        />
      );
    } else if (daysLeft != null) {
      usageMark = (
        <Badge variant="secondary" className="px-1.5 py-0 font-medium">
          {daysLeft === 0
            ? t("communityLayout.tabBadge.trialLastDay")
            : t("communityLayout.tabBadge.trial", { count: daysLeft })}
        </Badge>
      );
    }
    return usageMark
      ? tabs.map((tab) => (tab.value === "usage" ? { ...tab, adornment: usageMark } : tab))
      : tabs;
  }, [tabs, summary, t]);

  // Running any part of the community: held as its admin, by a custom role,
  // or lent by a settings grant.
  const canViewSettings = tabs.length > 0;

  if (isLoading) {
    return <SettingsPaneSkeleton />;
  }

  if (!canViewSettings) {
    return (
      <div className="space-y-6">
        <h1 className="font-semibold text-3xl tracking-tight">{t("communityLayout.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("communityLayout.permissionDenied")}</p>
      </div>
    );
  }

  // Normalize path for tab matching
  const currentPath = location.pathname;
  const normalizedPath = isCommunityScopedPath(currentPath)
    ? extractSubPath(currentPath).replace(/\/+$/, "") || "/"
    : currentPath.replace(/\/+$/, "") || "/";

  // Derived from the tabs themselves rather than restated: a second hand-kept
  // list is a tab that highlights the wrong one the day someone adds a tab and
  // updates only the list they happened to be looking at. The tab paths are
  // community-prefixed; matching happens on the sub-path.
  const tabSubPaths = communitySettingsTabs.map((tab) => ({
    value: tab.value,
    path: extractSubPath(tab.path),
  }));

  const activeTab = matchActiveTab(
    tabSubPaths,
    normalizedPath,
    communitySettingsTabs[0]?.value ?? "community"
  );

  // A read-only community shows the admin a prominent notice pointing them to the
  // platform operator (the status reaches admins only — see the backend
  // CommunityRead serialization). A suspended one never reaches settings at all.
  const statusNotice =
    activeCommunity?.status === "read_only"
      ? {
          message: t("communityLayout.restricted.read_only.message"),
        }
      : null;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-semibold text-3xl tracking-tight">{t("communityLayout.title")}</h1>
        </div>
        {statusNotice && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="font-bold text-destructive text-sm">{statusNotice.message}</p>
            <HelpLink topic={SupportTopic.community} communityId={activeCommunity?.id ?? null} />
          </div>
        )}
        {!changesSettings && (
          <p className="text-muted-foreground text-sm">{t("communityLayout.viewOnly")}</p>
        )}
      </div>
      <SettingsTabsNav
        tabs={communitySettingsTabs}
        activeTab={activeTab}
        onNavigate={(path) => router.navigate({ to: path })}
      />
      <fieldset disabled={!changesSettings} className="m-0 min-w-0 border-0 p-0">
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </fieldset>
    </div>
  );
};
