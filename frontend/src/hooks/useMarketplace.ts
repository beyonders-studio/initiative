/**
 * Reading the marketplace catalog.
 *
 * The catalog is one shared surface addressed by globally unique ids, and no
 * listing carries a community — but *which* of it a community is offered does depend on
 * the community asking: a dashboard a plug-in ships with itself appears only where the
 * plug-in is installed. So every read here is community-addressed and keyed per community,
 * the shelf and a single listing alike, and the answer a card gives is the
 * answer the page it opens gives.
 *
 * Whether a listing is *installed here* is a separate per-community question the
 * dashboards and plug-ins endpoints answer; the surface merges those in client-side.
 *
 * A listing's page is read in the reader's language: a plug-in this community
 * cannot install yet carries how the deployment's billing sells it here, worded
 * by billing. That answer changes in another tab — the seat buys in the billing
 * portal, and the statement that lets the plug-in install arrives seconds later —
 * so a listing that is unavailable is read again whenever this tab comes back,
 * however fresh it is.
 */

import { keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  ListMarketplaceListingsParams,
  MarketplaceListingDetail,
  MarketplaceListingPage,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useListMarketplaceListings,
  useReadMarketplaceListing,
  useResolveMarketplaceListing,
} from "@/api/generated/marketplace/marketplace";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { QueryOpts } from "@/types/query";

/** The catalog changes when a deployment is upgraded or a registry refresh
 *  runs, not while someone is browsing. */
const CATALOG_STALE_MS = 5 * 60 * 1000;

/** Back in this tab: a listing this community cannot install yet is read
 *  again at once, since the way to install it is in another tab. */
const refetchUnavailableOnFocus = (query: { state: { data?: MarketplaceListingDetail } }) =>
  query.state.data?.unavailable ? ("always" as const) : true;

/** The reader's language, which a listing's offer is worded in. */
const useReaderLocale = () => {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage ?? i18n.language;
};

export const useMarketplaceListings = (
  params?: ListMarketplaceListingsParams,
  options?: QueryOpts<MarketplaceListingPage>
) => {
  const communityId = useActiveCommunityId();
  return useListMarketplaceListings(communityId, params, {
    query: {
      // Typing keeps the previous page on screen while the next one loads, so the
      // grid does not blank out on every keystroke.
      placeholderData: keepPreviousData,
      staleTime: CATALOG_STALE_MS,
      ...options,
    },
  });
};

export const useMarketplaceListing = (
  publicId: string | null,
  options?: QueryOpts<MarketplaceListingDetail>
) => {
  const communityId = useActiveCommunityId();
  const locale = useReaderLocale();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useReadMarketplaceListing(
    communityId,
    publicId ?? "",
    { locale },
    {
      query: {
        enabled: Boolean(publicId) && userEnabled,
        staleTime: CATALOG_STALE_MS,
        refetchOnWindowFocus: refetchUnavailableOnFocus,
        ...rest,
      },
    }
  );
};

/**
 * The listing behind an installed instance.
 *
 * An install stores its listing's uid, not its public id — the uid is the stable
 * identity across deployments — so finding "where did this come from, and is
 * there a newer version?" goes through the uid.
 */
export const useMarketplaceListingByUid = (
  uid: string | null | undefined,
  options?: QueryOpts<MarketplaceListingDetail>
) => {
  const communityId = useActiveCommunityId();
  const locale = useReaderLocale();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useResolveMarketplaceListing(
    communityId,
    uid ?? "",
    { locale },
    {
      query: {
        enabled: Boolean(uid) && userEnabled,
        staleTime: CATALOG_STALE_MS,
        refetchOnWindowFocus: refetchUnavailableOnFocus,
        // A listing this community cannot take is a real answer for an installed
        // dashboard — withdrawn, or a plug-in it no longer has — not something to
        // retry.
        retry: false,
        ...rest,
      },
    }
  );
};
