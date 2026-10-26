import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  bulkDeleteCatalogItems,
  deleteCatalogItem,
  deleteCatalogItemVersion,
  getCatalogItemTimeline,
  getGetCatalogItemTimelineQueryKey,
  getListCatalogItemsQueryKey,
  getListCatalogItemVersionsQueryKey,
  getReadCatalogItemQueryKey,
  listCatalogItems,
  listCatalogItemVersions,
  updateCatalogItem,
  uploadCatalogItem,
  uploadCatalogItemVersion,
} from "@/api/generated/catalogs/catalogs";
import type {
  CatalogItemBulkDelete,
  CatalogItemBulkDeleteResponse,
  CatalogItemListResponse,
  CatalogItemRead,
  CatalogItemUpdate,
  CatalogItemVersionRead,
  GetCatalogItemTimelineParams,
  ListCatalogItemsParams,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { compose, invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const catalogs = TOOL_HOOKS[Tool.catalog];
export const useCatalogsList = catalogs.useList;
export const useCatalog = catalogs.useDetail;
export const useUpdateCatalog = catalogs.useUpdate;
export const useDeleteCatalog = catalogs.useDelete;
export const useSetCatalogGrants = catalogs.useSetGrants;

// ── Pictures ────────────────────────────────────────────────────────────────

/** The filters a catalog's picture list takes, without the page. */
export type CatalogItemsParams = Omit<ListCatalogItemsParams, "page">;

/**
 * A catalog's pictures, page by page, as somebody scrolls the wall.
 *
 * An infinite query rather than a page in the URL: a wall is scrolled, not
 * paged through, and what a page bounds is how much is fetched ahead of the
 * reader. `keepPreviousData` keeps the wall on screen while a changed filter
 * loads rather than blanking it.
 */
export const useCatalogItemsFeed = (catalogId: number | null, params?: CatalogItemsParams) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getListCatalogItemsQueryKey(communityId, catalogId!, params),
    queryFn: ({ pageParam }) =>
      listCatalogItems(communityId, catalogId!, {
        ...params,
        page: pageParam as number,
      }),
    initialPageParam: 1,
    getNextPageParam: (last: CatalogItemListResponse) =>
      last.has_next ? last.page + 1 : undefined,
    placeholderData: keepPreviousData,
    enabled: catalogId !== null && Number.isFinite(catalogId),
  });
};

/**
 * The months a catalog has pictures in — what the timeline rail is drawn from.
 * Takes the same filters the feed does, so the rail is a picture of the feed
 * as it currently stands.
 */
export const useCatalogItemsTimeline = (
  catalogId: number | null,
  params?: GetCatalogItemTimelineParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TimelineResponse>({
    queryKey: getGetCatalogItemTimelineQueryKey(communityId, catalogId!, params),
    queryFn: () => getCatalogItemTimeline(communityId, catalogId!, params),
    enabled: catalogId !== null && Number.isFinite(catalogId) && userEnabled,
    ...rest,
  });
};

/** Every stored rendition of one picture. Fetched when somebody opens the
 *  picture's details — a wall of forty must not fetch forty histories. */
export const useCatalogItemVersions = (
  catalogId: number,
  itemId: number | null,
  options?: QueryOpts<CatalogItemVersionRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<CatalogItemVersionRead[]>({
    queryKey: getListCatalogItemVersionsQueryKey(communityId, itemId!),
    queryFn: () => listCatalogItemVersions(communityId, itemId!),
    enabled: itemId !== null && userEnabled,
    ...rest,
  });
};

/** A picture changed, so the wall, the rail, and the catalog's own count and
 *  cover are all stale. */
export const invalidateImages = (catalogId: number) =>
  invalidate(q.toolSubtree(Tool.catalog, catalogId), q.catalogItems(catalogId), q.allCatalogs());

export interface UploadCatalogItemVariables {
  file: File;
  title?: string | null;
  caption?: string | null;
}

/**
 * Add one picture. One request per file — a drop of forty is forty of these,
 * run a few at a time by the uploader, so one failure does not take the rest
 * with it.
 *
 * Deliberately invalidates nothing and toasts nothing: the uploader that
 * drives it refreshes the wall a few times over a drop rather than once per
 * picture — forty refetches of the list in a minute is a rate limit — and
 * reports failures per file, where forty toasts would be forty toasts.
 */
export const useUploadCatalogItem = (
  catalogId: number,
  options?: MutationOpts<CatalogItemRead, UploadCatalogItemVariables>
) =>
  useCommunityMutation<CatalogItemRead, UploadCatalogItemVariables>(
    {
      mutationFn: (communityId, { file, title, caption }) =>
        uploadCatalogItem(communityId, catalogId, {
          file,
          title: title ?? null,
          caption: caption ?? null,
        }),
    },
    options
  );

export const useDeleteCatalogItem = (catalogId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, itemId) => deleteCatalogItem(communityId, itemId),
      invalidate: () => invalidateImages(catalogId),
      errorKey: "catalogs:error",
    },
    options
  );

/**
 * Send a selection of pictures to the trash together.
 *
 * One request, not one per picture: forty deletes would be forty round trips
 * and forty chances to half-succeed, where the endpoint refuses the whole
 * selection if any id is not this catalog's own.
 */
export const useBulkDeleteCatalogItems = (
  catalogId: number,
  options?: MutationOpts<CatalogItemBulkDeleteResponse, number[]>
) =>
  useCommunityMutation<CatalogItemBulkDeleteResponse, number[]>(
    {
      mutationFn: (communityId, itemIds) =>
        bulkDeleteCatalogItems(communityId, catalogId, {
          item_ids: itemIds,
        } satisfies CatalogItemBulkDelete),
      invalidate: () => invalidateImages(catalogId),
      errorKey: "catalogs:error",
    },
    options
  );

export const useUploadCatalogItemVersion = (
  catalogId: number,
  options?: MutationOpts<CatalogItemVersionRead, { itemId: number; file: File }>
) =>
  useCommunityMutation<CatalogItemVersionRead, { itemId: number; file: File }>(
    {
      mutationFn: (communityId, { itemId, file }) =>
        uploadCatalogItemVersion(communityId, itemId, { file }),
      invalidate: () => invalidateImages(catalogId),
      errorKey: "catalogs:error",
    },
    options
  );

export const useDeleteCatalogItemVersion = (
  catalogId: number,
  options?: MutationOpts<void, { itemId: number; versionId: number }>
) =>
  useCommunityMutation<void, { itemId: number; versionId: number }>(
    {
      mutationFn: (communityId, { itemId, versionId }) =>
        deleteCatalogItemVersion(communityId, itemId, versionId),
      invalidate: () => invalidateImages(catalogId),
      errorKey: "catalogs:error",
    },
    options
  );

/** How a catalog's pictures are saved field by field. */
export const catalogItemSaves = (
  catalogId: number
): FieldSaveKind<CatalogItemRead, CatalogItemUpdate> => ({
  name: "catalog-item",
  readKey: (communityId, id) => getReadCatalogItemQueryKey(communityId, id),
  patch: (communityId, id, patch) => updateCatalogItem(communityId, id, patch),
  properties: PropertyTarget.catalog_item,
  lists: () =>
    compose(q.toolSubtree(Tool.catalog, catalogId), q.catalogItems(catalogId), q.allCatalogs()),
  itself: (id) => q.catalogItem(id),
});
