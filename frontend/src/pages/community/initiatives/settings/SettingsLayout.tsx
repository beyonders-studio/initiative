/**
 * The frame around one initiative's settings: who you're configuring, the tab
 * bar, and whichever section the address names.
 *
 * The sections are real routes — `/settings/members` is a place, not a piece of
 * component state — so a manager can link someone straight to the join-request
 * queue, and the back button walks back through the sections they visited. The
 * bar still looks and behaves like tabs; selecting one navigates.
 *
 * Everything that decides whether the settings exist at all lives here: a bad
 * id, an initiative this reader can't see, and the standing to configure it.
 * A section that needs more than that says so itself (see
 * `SettingsPermissionRequired`) — the outlet is not a permission.
 */

import { Link, Navigate, Outlet } from "@tanstack/react-router";
import { Suspense, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsPageHeader } from "@/components/settings/SettingsPageHeader";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { SettingsTabsNav } from "@/components/settings/SettingsTabsNav";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useCommunityPath } from "@/lib/communityUrl";
import { initiativeRoute } from "@/lib/tools";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList } from "@/ui/breadcrumb";
import { Button } from "@/ui/button";
import {
  DetailPageSkeleton,
  FormSkeleton,
  PageHeaderSkeleton,
  SettingsPaneSkeleton,
  SkeletonRegion,
} from "@/ui/page-skeletons";

export const SettingsLayout = () => {
  const { t } = useTranslation(["initiatives", "properties"]);
  const gp = useCommunityPath();

  const {
    initiativeId,
    hasValidInitiativeId,
    initiative,
    isLoading,
    canManageMembers,
    canDeleteInitiative,
  } = useInitiativeSettings();

  const settingsRoute = `${initiativeRoute(initiativeId)}/settings`;

  const tabs = useMemo(
    () => [
      { value: "details", label: t("settings.detailsTab"), path: gp(settingsRoute) },
      { value: "members", label: t("settings.membersTab"), path: gp(`${settingsRoute}/members`) },
      { value: "roles", label: t("settings.rolesTab"), path: gp(`${settingsRoute}/roles`) },
      {
        value: "properties",
        label: t("properties:manager.title"),
        path: gp(`${settingsRoute}/properties`),
      },
      {
        value: "layouts",
        label: t("settings.layoutsTab"),
        path: gp(`${settingsRoute}/layouts`),
      },
      // Aggregate export is managers+ (the community-wide variant lives in community
      // settings, admin-gated). The route refuses it too — this only keeps the
      // bar honest about where the reader can go.
      {
        value: "export",
        label: t("settings.exportTab"),
        path: gp(`${settingsRoute}/export`),
        visible: canManageMembers,
      },
      { value: "danger", label: t("settings.dangerTab"), path: gp(`${settingsRoute}/danger`) },
    ],
    [t, gp, settingsRoute, canManageMembers]
  );

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/")} replace />;
  }

  if (isLoading) {
    return (
      <SkeletonRegion className="space-y-6">
        <DetailPageSkeleton actions={0} description={false}>
          <PageHeaderSkeleton title={false} tabs={5} />
          <FormSkeleton />
        </DetailPageSkeleton>
      </SkeletonRegion>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-6">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp("/")}>{t("settings.backToInitiatives")}</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="font-semibold text-3xl tracking-tight">{t("settings.notFound")}</h1>
          <p className="text-muted-foreground">{t("settings.notFoundDescription")}</p>
        </div>
      </div>
    );
  }

  if (!canManageMembers && !canDeleteInitiative) {
    return (
      <div className="space-y-6">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp(initiativeRoute(initiative.id))}>{t("settings.backToInitiative")}</Link>
        </Button>
        <SettingsPermissionRequired scope="initiative" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(initiativeRoute(initiative.id))}>{initiative.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <SettingsPageHeader title={t("settings.title")} />

      <SettingsTabsNav tabs={tabs} />
      <Suspense fallback={<SettingsPaneSkeleton />}>
        <Outlet />
      </Suspense>
    </div>
  );
};
