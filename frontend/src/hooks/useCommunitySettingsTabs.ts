import { useParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { SettingsTab } from "@/components/settings/SettingsTabsNav";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { communityPath } from "@/lib/communityUrl";

/**
 * The community settings tabs this person may open, in order, with
 * community-scoped paths.
 *
 * One list for the tab bar and for where `/settings` itself sends you: the
 * first tab here is the landing page, so nobody is sent to a tab they would be
 * refused. The seat's tabs follow the seat; the rest follow the parts of
 * running the community the reader holds. `isLoading` is true until the
 * server has said which those are.
 */
export const useCommunitySettingsTabs = (): { tabs: SettingsTab[]; isLoading: boolean } => {
  const { t } = useTranslation(["settings"]);
  const { activeCommunity, activeCommunityId } = useCommunities();
  // Reaching the work inside the community, which a settings grant does not —
  // the tabs built on content are dropped below rather than rendered into
  // refusals.
  const reachesContent = Boolean(activeCommunity?.can.content);
  const held = useHeldSurfaces();
  const { holds } = held;
  // The seat above admin, which holds this community's sign-in and its
  // integrations — held outright, or lent for a window by a settings grant.
  const onTheGrantedSeat = activeCommunity?.grantSettingsLevel === "superadmin";
  const isSuperadmin = Boolean(activeCommunity?.can.seat);
  // Where the deployment has a billing portal, the plan sits with the usage.
  const { billing, guestsEnabled } = useAppConfig();
  // Guests are invited by whoever hands out invites on the admin rung: a guest
  // invite can open any initiative, which takes the admin's view of all of
  // them. And only where the deployment allows guests and the community takes
  // them.
  const managesGuests =
    held.writes &&
    holds("invites") &&
    Boolean(activeCommunity?.can.administer) &&
    guestsEnabled &&
    activeCommunity?.max_guests !== 0;
  // Where the community has a sign-in of its own to configure, that is. Most
  // never do: the operator grants each half of the surface separately, and
  // with neither there is nothing on the tab to show anybody. A grantee's
  // entry carries no options — the page reads the real ones and shows nothing
  // where there are none.
  const authOptions = activeCommunity?.auth_options ?? [];
  const configuresItsOwnSignIn =
    isSuperadmin &&
    (onTheGrantedSeat || authOptions.includes("providers") || authOptions.includes("restrictions"));
  const params = useParams({ strict: false }) as { communityId?: string };
  // Get community ID from URL params or active community
  const urlCommunityId = params.communityId ? Number(params.communityId) : activeCommunityId;

  const tabs = useMemo(() => {
    const path = (section: string) =>
      urlCommunityId
        ? communityPath(urlCommunityId, `/settings/${section}`)
        : `/settings/${section}`;
    const tabs: SettingsTab[] = [
      // First, so the seat lands on it: what the community uses against its
      // caps, and — where there is a portal — the plan those caps come with.
      // Both are the seat's, like its sign-in; an ordinary admin runs the
      // community without holding its card.
      {
        value: "usage",
        label: billing ? t("communityLayout.tabs.planAndUsage") : t("communityLayout.tabs.usage"),
        path: path("usage"),
        visible: isSuperadmin,
      },
      {
        value: "community",
        label: t("communityLayout.tabs.community"),
        path: path("community"),
        visible: holds("profile"),
      },
      {
        value: "users",
        label: t("communityLayout.tabs.users"),
        path: path("users"),
        visible: holds("members") || holds("invites"),
      },
      {
        value: "roles",
        label: t("communityLayout.tabs.roles"),
        path: path("roles"),
        visible: holds("roles"),
      },
      {
        value: "guests",
        label: t("communityLayout.tabs.guests"),
        path: path("guests"),
        visible: managesGuests,
      },
      // Everything on this tab is the superadmin's to set, so the tab is
      // theirs too — an ordinary admin has nothing to do on it.
      {
        value: "security",
        label: t("communityLayout.tabs.security"),
        path: path("security"),
        visible: configuresItsOwnSignIn,
      },
      {
        value: "initiatives",
        label: t("communityLayout.tabs.initiatives"),
        path: path("initiatives"),
        visible: reachesContent && holds("initiatives"),
      },
      // What the community hands to somebody outside it — an AI provider, a
      // plug-in — is the seat's to decide, the way its sign-in is. An ordinary
      // admin runs the community; these say who else gets to see it.
      {
        value: "integrations",
        label: t("communityLayout.tabs.integrations"),
        path: path("integrations"),
        visible: isSuperadmin,
      },
      {
        value: "trash",
        label: t("communityLayout.tabs.trash"),
        path: path("trash"),
        visible: reachesContent && holds("trash"),
      },
      // Taking the community's every initiative out in one file, or putting
      // one back, reaches as far as deleting it does — so it sits with the
      // same seat. An ordinary admin runs the community; this one moves it.
      {
        value: "data",
        label: t("communityLayout.tabs.data"),
        path: path("data"),
        visible: isSuperadmin,
      },
      // Danger zone lives last — destructive community deletion is deliberately
      // tucked behind its own tab rather than the first screen — and only the
      // seat sees it. Deleting a community is the one action an admin could not
      // undo and could not have undone for them; it belongs with the seat a
      // restore needs, which is also the seat the receipt is written to.
      {
        value: "danger-zone",
        label: t("communityLayout.tabs.dangerZone"),
        path: path("danger-zone"),
        visible: isSuperadmin,
      },
    ];
    return tabs.filter((tab) => tab.visible);
  }, [
    urlCommunityId,
    t,
    configuresItsOwnSignIn,
    isSuperadmin,
    reachesContent,
    billing,
    managesGuests,
    holds,
  ]);
  return { tabs, isLoading: held.isLoading };
};
