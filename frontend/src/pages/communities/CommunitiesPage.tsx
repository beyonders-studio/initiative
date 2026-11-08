/**
 * The community directory, as a place you browse.
 *
 * The cards, and only the cards. What narrows them — the search box and the
 * shelves a community can file itself under — is the app's sidebar while this page
 * is open (``CommunityDirectorySidebar``), which is where every other place in
 * the app keeps what it is browsed by. The two agree through the URL: the
 * sidebar writes ``q`` and ``category``, this reads them, and a filtered
 * directory is therefore a link.
 *
 * The directory is platform-level, so this asks nothing about the caller's
 * current community. Whether they are already in one of these is answered by the
 * card payload itself.
 *
 * Whether there is a directory at all is the platform owner's setting. Where it
 * is off the page still exists — it can be linked to, and a link should say
 * what happened — but it says so instead of searching. A client that had not
 * heard yet asks and is refused, which lands in the same place: the server's
 * answer is what settles it, not the config this page loaded with.
 */

import { useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { CommunityCard } from "@/components/communities/CommunityCard";
import { CommunitySearchField } from "@/components/communities/CommunitySearchField";
import { DirectoryNearControl } from "@/components/communities/DirectoryNearControl";
import { PageBanner } from "@/components/PageBanner";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useDirectoryCommunities } from "@/hooks/useCommunityDirectory";
import { renderableBanner } from "@/lib/banner";
import { asCommunityCategories } from "@/lib/communityCategories";
import { countriesNamedBy } from "@/lib/communityLocation";
import {
  effectiveNear,
  nearSearchFrom,
  nearSearchOf,
  parseSavedNear,
  savedNearSnapshot,
  subscribeSavedNear,
} from "@/lib/directoryNear";
import { getErrorCode } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

/** Stable keys for the loading placeholders — an index key on a list that can
 *  change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function CommunitiesPage() {
  const { t, i18n } = useTranslation(["communities", "common"]);
  // Read loosely and re-narrowed here rather than trusted from the route:
  // `useSearch({ strict: false })` returns the params as they are and does not
  // run the route's `validateSearch`, so anywhere this page is mounted another
  // way an unrecognized value would otherwise filter the grid down to nothing.
  const rawSearch = useSearch({ strict: false }) as Record<string, unknown>;
  const categories = asCommunityCategories(rawSearch.category);
  const search = typeof rawSearch.q === "string" ? rawSearch.q : "";

  const { communityDirectoryEnabled, isLoading: configLoading } = useAppConfig();

  // Where a community is counts as much as what it is called: the search also
  // reaches its location, and a country is stored as a code, so the countries
  // the words name go along with them.
  const query = search.trim();
  const queryCountries = useMemo(
    () => (query ? countriesNamedBy(query, i18n.resolvedLanguage ?? i18n.language ?? "en") : []),
    [query, i18n.resolvedLanguage, i18n.language]
  );

  // Where the reader is: the address's place, else the one kept on this
  // device. It sorts the nearest first and narrows nothing.
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const savedNear = useSyncExternalStore(subscribeSavedNear, () => savedNearSnapshot(userId));
  const nearKey = JSON.stringify(nearSearchFrom(rawSearch));
  // biome-ignore lint/correctness/useExhaustiveDependencies: nearKey is the address's place, by value
  const near = useMemo(
    () => effectiveNear(nearSearchFrom(rawSearch), parseSavedNear(savedNear)),
    [nearKey, savedNear]
  );

  // The words for the place are the reader's own; the endpoint needs only
  // where it is.
  const { near_place: _words, ...nearParams } = nearSearchOf(near);

  const directory = useDirectoryCommunities(
    {
      search: query || undefined,
      search_country: queryCountries.length ? queryCountries : undefined,
      ...nearParams,
      category: categories.length ? categories : undefined,
    },
    { enabled: communityDirectoryEnabled }
  );

  // The grid is a shelf that grows, so the loaded pages are shown as one list.
  const communities = directory.data?.pages.flatMap((page) => page.items) ?? [];
  // How many matched, not how many are on screen — every page carries the
  // same figure, so the first one answers it.
  const total = directory.data?.pages[0]?.total_count ?? 0;

  // Either this client was told there is no directory, or it asked and was told
  // so. The second is how a tab that was open when an owner switched it off
  // finds out — a refusal is an answer, not the momentary failure the
  // unavailable message describes.
  const directoryOff =
    !communityDirectoryEnabled || getErrorCode(directory.error) === "COMMUNITY_DIRECTORY_DISABLED";

  // The page's title sits centred on the banner rather than above it, in the
  // same frame a community's front page uses — see ``PageBanner``. The artwork is
  // fixed and light-toned, and its lower edge fades out in the file itself, so
  // what it fades into is the page.
  const hero = (
    <PageBanner
      // The artwork ships with the app rather than being served per community, so
      // it needs no resolving; the rest is what a header with no community banner
      // behind it looks like.
      banner={{ ...renderableBanner(), image_url: "/images/community-banner.webp" }}
      haloOverImage
      title={t("communities:community.heroTitle")}
      subtitle={t("communities:community.heroSubtitle")}
    />
  );

  // No directory on this deployment: no search box, no shelves, and no request.
  if (!configLoading && directoryOff) {
    return (
      <div className="space-y-6">
        {hero}
        <StatusMessage
          icon={<CloudOff />}
          title={t("communities:community.disabledTitle")}
          description={t("communities:community.disabledDescription")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {hero}

      {/* Below `lg` the sidebar this normally sits in is off-canvas, so the
          page carries the search rather than making someone open a drawer to
          reach it. The shelves stay in the sidebar: they are a list of twelve,
          and the search is the one that answers "is my thing here at all". */}
      <CommunitySearchField className="md:hidden" />

      <DirectoryNearControl near={near} />

      {directory.isError ? (
        // A directory that failed to answer is not a directory with nothing
        // in it, and saying so would send someone looking for communities that exist.
        <StatusMessage
          icon={<CloudOff />}
          title={t("communities:community.unavailableTitle")}
          description={t("communities:community.unavailableDescription")}
        />
      ) : configLoading || directory.isLoading ? (
        <div className="grid grid-cols-fill-72/3 gap-4">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-52 w-full rounded-xl" />
          ))}
        </div>
      ) : communities.length ? (
        <>
          <p className="text-muted-foreground text-sm">
            {t("communities:community.resultCount", { count: total })}
          </p>
          <div className="grid grid-cols-fill-72/3 gap-4">
            {communities.map((community) => (
              <CommunityCard key={community.id} community={community} />
            ))}
          </div>
          {directory.hasNextPage ? (
            <div className="flex justify-center pt-2">
              <Button
                variant="outline"
                onClick={() => void directory.fetchNextPage()}
                disabled={directory.isFetchingNextPage}
              >
                {t("communities:community.showMore")}
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <StatusMessage
          icon={<SearchX />}
          title={
            search
              ? t("communities:community.noResultsTitle")
              : t("communities:community.emptyTitle")
          }
          description={
            search
              ? t("communities:community.noResultsDescription", { query: search })
              : t("communities:community.emptyDescription")
          }
        />
      )}
    </div>
  );
}
