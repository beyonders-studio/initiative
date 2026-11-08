/**
 * The marketplace, as a place you browse.
 *
 * A searchable card grid rather than a menu: listings are products with artwork,
 * an author, and a description, and picking one is a decision worth a page.
 *
 * The shelf is community-addressed: a dashboard a plug-in ships with itself appears
 * only where the plug-in is installed, so the catalog is asked on this community's
 * behalf. What is already installed here is a second question, answered by the
 * community's own dashboards and plug-ins lists and matched up client-side.
 * Other shelves ask nothing: a project installs as a new copy every time, so
 * there is no "already have it" to show.
 */

import { useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useInstalledListings } from "@/hooks/useDashboards";
import { useMarketplaceListings } from "@/hooks/useMarketplace";
import { type CommunityShelf, parseCommunityShelf } from "@/lib/marketplace";
import { catalogueSources, listingShownHere } from "@/lib/marketplaceCuration";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

const PAGE_SIZE = 24;
/** One line per shelf, so a new kind shows its own rather than the dashboards'.
 *  Keyed on the shelves themselves, so adding one to `COMMUNITY_SHELVES`
 *  without a line of its own does not compile. */
const SUBTITLE_KEYS = {
  [ListingKind.dashboard]: "subtitle",
  [ListingKind.project]: "subtitleProjects",
  [ListingKind.plugin]: "subtitlePlugins",
  [ListingKind.auto]: "subtitleAuto",
} as const satisfies Record<CommunityShelf, string>;
/** Stable keys for the loading placeholders — they never reorder, and an index
 *  key on a list that can change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function MarketplaceBrowsePage() {
  const { t } = useTranslation("marketplace");
  // Which shelf: dashboards, or the plug-ins a community admin adds.
  //
  // Normalized here through the same parser the route validates with, not left
  // to the route. `useSearch({ strict: false })` reads the params as they are —
  // it does not run the route's `validateSearch` — so relying on that would
  // mean the filter silently disappears anywhere the page is mounted another
  // way, and the grid would mix plug-ins into the dashboards.
  const search_ = useSearch({ strict: false });
  const kind = parseCommunityShelf(search_.kind);
  const [query, setQuery] = useState("");
  // The catalog is a network call per keystroke otherwise, and the grid keeps
  // the previous page while the next one loads.
  const search = useDebouncedValue(query, 250);

  // The iPhone app asks for the curated catalogue only, and filters the answer
  // as well so nothing else can reach a card there.
  const listingsQuery = useMarketplaceListings({
    kind,
    search: search.trim() || undefined,
    source: catalogueSources(),
    page_size: PAGE_SIZE,
  });

  // Which of these this community already has. Each shelf has to ask its own tool:
  // the dashboards aggregate knows nothing about plug-ins, so using it on the plug-ins
  // shelf would report every plug-in as not installed.
  //
  // Left undefined when the request failed, rather than defaulted to an empty
  // map: "we do not know" and "you have none of these" look identical on a card,
  // and only one of them is true. The notice below says which.
  const dashboardInstalls = useInstalledListings({ enabled: kind === ListingKind.dashboard });
  const pluginInstalls = useCommunityPlugins({ enabled: kind === ListingKind.plugin });
  const installedQuery =
    kind === ListingKind.plugin
      ? pluginInstalls
      : kind === ListingKind.dashboard
        ? dashboardInstalls
        : null;

  const installedByUid = useMemo(() => {
    if (!installedQuery || installedQuery.isError) return undefined;
    if (kind === ListingKind.plugin) {
      // One install per listing per community, so this is a presence map that
      // happens to be shaped like the dashboards' counts.
      const counts: Record<string, number> = {};
      for (const plugin of pluginInstalls.data?.items ?? []) counts[plugin.listing_uid] = 1;
      return counts;
    }
    return dashboardInstalls.data?.counts;
  }, [kind, installedQuery, pluginInstalls.data, dashboardInstalls.data]);

  const listings = (listingsQuery.data?.items ?? []).filter(listingShownHere);

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t(SUBTITLE_KEYS[kind])}</p>
      </div>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className="max-w-md"
      />

      {listingsQuery.isError ? (
        // A catalog that failed to answer is not a catalog with nothing in it,
        // and saying so would send someone looking for listings that exist.
        <StatusMessage
          icon={<CloudOff />}
          title={t("unavailable.title")}
          description={t("unavailable.description")}
        />
      ) : listingsQuery.isLoading ? (
        <div className="grid grid-cols-fill-72/3 gap-4">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : listings.length ? (
        <>
          {installedQuery?.isError && (
            <p className="text-muted-foreground text-sm">{t("installedUnknown")}</p>
          )}
          <div className="grid grid-cols-fill-72/3 gap-4">
            {listings.map((listing) => (
              <MarketplaceCard
                key={listing.public_id}
                listing={listing}
                installedCount={installedByUid?.[listing.uid] ?? 0}
              />
            ))}
          </div>
        </>
      ) : (
        <StatusMessage
          icon={<SearchX />}
          title={search ? t("noResults.title") : t("empty.title")}
          description={
            search ? t("noResults.description", { query: search }) : t("empty.description")
          }
        />
      )}
    </div>
  );
}
