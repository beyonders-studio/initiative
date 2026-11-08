import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { createCommunityBillingHandoff } from "@/api/generated/communities/communities";
import { useAppConfig } from "@/hooks/useAppConfig";
import { openExternal, reserveTab as reserveBlankTab } from "@/lib/openExternal";
import { sellsOnThisDevice, useStoreSellingAnswer } from "@/lib/storeSelling";

/** Portal page to land on: the plan/card setup screen, or the existing
 *  subscription's management screen. */
export type BillingPortalPage = "manage" | "upgrade";

/** What a portal page opens on: a catalog tier picked beforehand (`plan`),
 *  or a request to the deployment's owners for a plug-in its term has no
 *  seat free for (`request`, with the listing's uid). */
export interface BillingPortalQuery {
  plan?: string;
  request?: "plugin";
  listing?: string;
}

/**
 * Link-out to the external billing portal for one community.
 *
 * `billing` is null when the deployment has no portal configured (the
 * self-hosted default) — callers must skip every tier/upgrade/manage
 * affordance then, and `reserveTab`/`openPortal` become no-ops. It is also
 * null while the config is still loading, which `isLoading` tells apart.
 *
 * `portalUrl` is the address itself: the portal page for one community, with a
 * freshly minted handoff in its fragment. It throws when the server refuses
 * the handoff, and is null with no portal configured.
 *
 * `openPortal` opens that address in a new tab, falling back to the bare
 * portal page when the handoff fails. `openAddress` does the same for a portal
 * address the server handed out, such as where a community acts on a plug-in
 * it cannot install yet. The tab is opened before the handoff
 * token is minted so the browser keeps attributing it to the click that
 * started it. `reserveTab` exposes that step on its own for callers with their
 * own await between the click and the hop (community creation), which would
 * otherwise land the `window.open` outside the user gesture.
 *
 * `canSell` is whether this surface may lead anyone to a purchase: a portal
 * is configured and this device may sell (`@/lib/storeSelling` — always on the
 * web and the desktop app; on a phone only where its store allows a link to a
 * web purchase). Every upgrade/manage affordance asks `canSell`, not
 * `billing`, and `reserveTab`/`openPortal` do nothing where it is false.
 *
 * The phone apps open the portal in the system browser sheet rather than a
 * tab, so `reserveTab` returns null there.
 */
export const useBillingPortal = () => {
  const { billing, isLoading: configLoading } = useAppConfig();
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage ?? i18n.language;
  const sellsAnswer = useStoreSellingAnswer();
  const canSell = billing != null && sellsAnswer === true;
  // Still loading while a phone's store has not said whether it may sell, so
  // nothing decides on a `canSell` that is about to change.
  const isLoading = configLoading || (billing != null && sellsAnswer === undefined);
  const hasBilling = billing != null;

  /** `canSell`, once a phone's store has answered. */
  const sellsNow = useCallback(
    async (): Promise<boolean> => hasBilling && (await sellsOnThisDevice()),
    [hasBilling]
  );

  // No id of ours is in the address: the handoff in its fragment is what
  // names the community to the portal.
  const pageUrl = useCallback(
    (page: BillingPortalPage, query: BillingPortalQuery = {}): string | null => {
      if (!billing) return null;
      const params = new URLSearchParams({ lang });
      for (const name of ["plan", "request", "listing"] as const) {
        const value = query[name];
        if (value) params.set(name, value);
      }
      return `${billing.url}/${page}?${params.toString()}`;
    },
    [billing, lang]
  );

  const portalUrl = useCallback(
    async (communityId: number, page: BillingPortalPage): Promise<string | null> => {
      const base = pageUrl(page);
      if (!base) return null;
      const { handoff_token } = await createCommunityBillingHandoff(communityId);
      return `${base}#handoff=${encodeURIComponent(handoff_token)}`;
    },
    [pageUrl]
  );

  const reserveTab = useCallback(
    (): Window | null => (canSell ? reserveBlankTab() : null),
    [canSell]
  );

  // `selling` false for a page that sells nothing (a request to the
  // deployment's owners), which any device may open where there is a portal.
  const open = useCallback(
    async (
      communityId: number,
      base: string,
      reserved: Window | null | undefined,
      selling: boolean
    ) => {
      if (selling ? !canSell : !hasBilling) return;
      const tab = reserved ?? (selling ? reserveTab() : reserveBlankTab());
      let url = base;
      try {
        const { handoff_token } = await createCommunityBillingHandoff(communityId);
        url = `${base}#handoff=${encodeURIComponent(handoff_token)}`;
      } catch {
        // Without a handoff, the bare portal page.
      }
      openExternal(url, tab);
    },
    [canSell, hasBilling, reserveTab]
  );

  const openAddress = useCallback(
    (communityId: number, base: string, reserved?: Window | null) =>
      open(communityId, base, reserved, true),
    [open]
  );

  /** `query` says what the page opens on (see {@link BillingPortalQuery}). A
   *  request sells nothing, so it opens wherever there is a portal. */
  const openPortal = useCallback(
    async (
      communityId: number,
      page: BillingPortalPage,
      reserved?: Window | null,
      query?: BillingPortalQuery
    ) => {
      const base = pageUrl(page, query);
      if (!base) return;
      await open(communityId, base, reserved, !query?.request);
    },
    [open, pageUrl]
  );

  return {
    billing,
    canSell,
    isLoading,
    openAddress,
    openPortal,
    portalUrl,
    reserveTab,
    sellsNow,
  };
};
