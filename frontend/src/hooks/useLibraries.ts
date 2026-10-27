import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  bulkDeleteLibraryItems,
  deleteLibraryItem,
  deleteLibraryItemVersion,
  getLibraryItemTimeline,
  getGetLibraryItemTimelineQueryKey,
  getListLibraryItemsQueryKey,
  getListLibraryItemVersionsQueryKey,
  getReadLibraryItemQueryKey,
  listLibraryItems,
  listLibraryItemVersions,
  updateLibraryItem,
  uploadLibraryItem,
  uploadLibraryItemVersion,
} from "@/api/generated/libraries/libraries";
import type {
  LibraryItemBulkDelete,
  LibraryItemBulkDeleteResponse,
  LibraryItemListResponse,
  LibraryItemRead,
  LibraryItemUpdate,
  LibraryItemVersionRead,
  GetLibraryItemTimelineParams,
  ListLibraryItemsParams,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { compose, invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import type { FieldSaveKind } from "@/hooks/useFieldSave";
import { localDayKey } from "@/lib/formatDate";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const libraries = TOOL_HOOKS[Tool.library];
export const useLibrariesList = libraries.useList;
export const useLibrary = libraries.useDetail;
export const useUpdateLibrary = libraries.useUpdate;
export const useDeleteLibrary = libraries.useDelete;
export const useSetLibraryGrants = libraries.useSetGrants;

// ── Pictures ────────────────────────────────────────────────────────────────

/** The filters a library's picture list takes, without the page. */
export type LibraryItemsParams = Omit<ListLibraryItemsParams, "page">;

/**
 * A library's pictures, page by page, as somebody scrolls the wall.
 *
 * An infinite query rather than a page in the URL: a wall is scrolled, not
 * paged through, and what a page bounds is how much is fetched ahead of the
 * reader. `keepPreviousData` keeps the wall on screen while a changed filter
 * loads rather than blanking it.
 */
export const useLibraryItemsFeed = (libraryId: number | null, params?: LibraryItemsParams) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getListLibraryItemsQueryKey(communityId, libraryId!, params),
    queryFn: ({ pageParam }) =>
      listLibraryItems(communityId, libraryId!, {
        ...params,
        page: pageParam as number,
      }),
    initialPageParam: 1,
    getNextPageParam: (last: LibraryItemListResponse) =>
      last.has_next ? last.page + 1 : undefined,
    placeholderData: keepPreviousData,
    enabled: libraryId !== null && Number.isFinite(libraryId),
  });
};

/**
 * The months a library has pictures in — what the timeline rail is drawn from.
 * Takes the same filters the feed does, so the rail is a picture of the feed
 * as it currently stands.
 */
export const useLibraryItemsTimeline = (
  libraryId: number | null,
  params?: GetLibraryItemTimelineParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TimelineResponse>({
    queryKey: getGetLibraryItemTimelineQueryKey(communityId, libraryId!, params),
    queryFn: () => getLibraryItemTimeline(communityId, libraryId!, params),
    enabled: libraryId !== null && Number.isFinite(libraryId) && userEnabled,
    ...rest,
  });
};

/** Every stored rendition of one picture. Fetched when somebody opens the
 *  picture's details — a wall of forty must not fetch forty histories. */
export const useLibraryItemVersions = (
  libraryId: number,
  itemId: number | null,
  options?: QueryOpts<LibraryItemVersionRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<LibraryItemVersionRead[]>({
    queryKey: getListLibraryItemVersionsQueryKey(communityId, itemId!),
    queryFn: () => listLibraryItemVersions(communityId, itemId!),
    enabled: itemId !== null && userEnabled,
    ...rest,
  });
};

/** A picture changed, so the wall, the rail, and the library's own count and
 *  cover are all stale. */
export const invalidateImages = (libraryId: number) =>
  invalidate(q.toolSubtree(Tool.library, libraryId), q.libraryItems(libraryId), q.allLibraries());

export interface UploadLibraryItemVariables {
  file: File;
  title?: string | null;
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
export const useUploadLibraryItem = (
  libraryId: number,
  options?: MutationOpts<LibraryItemRead, UploadLibraryItemVariables>
) =>
  useCommunityMutation<LibraryItemRead, UploadLibraryItemVariables>(
    {
      mutationFn: (communityId, { file, title }) =>
        uploadLibraryItem(communityId, libraryId, {
          file,
          title: title ?? null,
          // Dated the day it is added where the person adding it is.
          occurred_on: localDayKey(new Date().toISOString()),
        }),
    },
    options
  );

export const useDeleteLibraryItem = (libraryId: number, options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, itemId) => deleteLibraryItem(communityId, itemId),
      invalidate: () => invalidateImages(libraryId),
      errorKey: "libraries:error",
    },
    options
  );

/**
 * Send a selection of pictures to the trash together.
 *
 * One request, not one per picture: forty deletes would be forty round trips
 * and forty chances to half-succeed, where the endpoint refuses the whole
 * selection if any id is not this library's own.
 */
export const useBulkDeleteLibraryItems = (
  libraryId: number,
  options?: MutationOpts<LibraryItemBulkDeleteResponse, number[]>
) =>
  useCommunityMutation<LibraryItemBulkDeleteResponse, number[]>(
    {
      mutationFn: (communityId, itemIds) =>
        bulkDeleteLibraryItems(communityId, libraryId, {
          item_ids: itemIds,
        } satisfies LibraryItemBulkDelete),
      invalidate: () => invalidateImages(libraryId),
      errorKey: "libraries:error",
    },
    options
  );

export const useUploadLibraryItemVersion = (
  libraryId: number,
  options?: MutationOpts<LibraryItemVersionRead, { itemId: number; file: File }>
) =>
  useCommunityMutation<LibraryItemVersionRead, { itemId: number; file: File }>(
    {
      mutationFn: (communityId, { itemId, file }) =>
        uploadLibraryItemVersion(communityId, itemId, { file }),
      invalidate: () => invalidateImages(libraryId),
      errorKey: "libraries:error",
    },
    options
  );

export const useDeleteLibraryItemVersion = (
  libraryId: number,
  options?: MutationOpts<void, { itemId: number; versionId: number }>
) =>
  useCommunityMutation<void, { itemId: number; versionId: number }>(
    {
      mutationFn: (communityId, { itemId, versionId }) =>
        deleteLibraryItemVersion(communityId, itemId, versionId),
      invalidate: () => invalidateImages(libraryId),
      errorKey: "libraries:error",
    },
    options
  );

/** How a library's pictures are saved field by field. */
export const libraryItemSaves = (
  libraryId: number
): FieldSaveKind<LibraryItemRead, LibraryItemUpdate> => ({
  name: "library-item",
  readKey: (communityId, id) => getReadLibraryItemQueryKey(communityId, id),
  patch: (communityId, id, patch) => updateLibraryItem(communityId, id, patch),
  properties: PropertyTarget.library_item,
  lists: () =>
    compose(q.toolSubtree(Tool.library, libraryId), q.libraryItems(libraryId), q.allLibraries()),
  itself: (id) => q.libraryItem(id),
});
