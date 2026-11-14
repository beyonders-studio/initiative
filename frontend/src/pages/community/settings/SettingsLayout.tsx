import { Outlet } from "@tanstack/react-router";
import { type ReactNode, Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { SettingsPageHeader } from "@/components/settings/SettingsPageHeader";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { HelpLink } from "@/components/support/HelpLink";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityBillingSummary } from "@/hooks/useCommunityBillingSummary";
import { useCommunitySettingsTabs } from "@/hooks/useCommunitySettingsTabs";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { trialDaysLeft } from "@/lib/billingSummary";
import { Badge } from "@/ui/badge";
import { SettingsPaneSkeleton } from "@/ui/page-skeletons";

export const SettingsLayout = () => {
  const { t } = useTranslation(["settings"]);
  const { activeCommunity } = useCommunities();
  // Whether what the reader holds may also be changed. Without it every
  // control on these pages is shown disabled.
  const changesSettings = useHeldSurfaces().writes;
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
      <SettingsPageHeader
        title={t("communityLayout.title")}
        description={t("communityLayout.permissionDenied")}
      />
    );
  }

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
      <SettingsPageHeader
        title={t("communityLayout.title")}
        description={changesSettings ? null : t("communityLayout.viewOnly")}
      >
        {statusNotice && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="font-bold text-destructive text-sm">{statusNotice.message}</p>
            <HelpLink topic={SupportTopic.community} communityId={activeCommunity?.id ?? null} />
          </div>
        )}
      </SettingsPageHeader>
      <SettingsTabsNav tabs={communitySettingsTabs} />
      <fieldset disabled={!changesSettings} className="m-0 min-w-0 border-0 p-0">
        <Suspense fallback={<SettingsPaneSkeleton />}>
          <Outlet />
        </Suspense>
      </fieldset>
    </div>
  );
};
