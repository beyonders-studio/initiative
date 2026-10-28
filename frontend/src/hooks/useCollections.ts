import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  addCollectionFiles,
  createCollection,
  deleteCollection,
  getCollectionFilesTimeline,
  getGetCollectionFilesTimelineQueryKey,
  getListCollectionFilesQueryKey,
  getListCollectionShapesQueryKey,
  getListCollectionsQueryKey,
  getReadCollectionQueryKey,
  listCollectionFiles,
  listCollectionShapes,
  listCollections,
  readCollection,
  removeCollectionFiles,
  setCollectionFileMetadata,
  updateCollection,
  uploadFile,
} from "@/api/generated/files/files";
import type {
  CollectionCreate,
  CollectionFileListResponse,
  CollectionListResponse,
  CollectionRead,
  CollectionShapeGroup,
  CollectionUpdate,
  FileRead,
  GetCollectionFilesTimelineParams,
  ListCollectionFilesParams,
  PropertySummary,
  PropertyValueInput,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { PropertyTarget } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { type FieldSaveKind, heldKey } from "@/hooks/useFieldSave";
import { nameWithoutExtension } from "@/lib/fileUtils";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** How many files a page of a collection's wall brings. */
const PAGE_SIZE = 60;

/** What a change to what is in a collection makes stale: every collection's
 *  card and list, and every file's read, which names its collections. */
export const invalidateCollectionContents = () => invalidate(q.allCollections(), q.allFiles());

/** An initiative's collections the reader can see, most recently changed
 *  first. */
export const useCollections = (initiativeId: number | null) => {
  const communityId = useActiveCommunityId();
  const params = { initiative_id: initiativeId ?? 0 };
  return useQuery<CollectionListResponse>({
    queryKey: getListCollectionsQueryKey(communityId, params),
    queryFn: () => listCollections(communityId, params),
    enabled: initiativeId !== null,
  });
};

/** The ready-made shapes a new collection can start as, in the reader's
 *  language, read again when it changes. They change only with a release. */
export const useCollectionShapes = (enabled: boolean) => {
  const communityId = useActiveCommunityId();
  const { i18n } = useTranslation();
  return useQuery<CollectionShapeGroup[]>({
    queryKey: [...getListCollectionShapesQueryKey(communityId), i18n.language],
    queryFn: () => listCollectionShapes(communityId),
    staleTime: Number.POSITIVE_INFINITY,
    enabled,
  });
};

export const useCollection = (collectionId: number | null) => {
  const communityId = useActiveCommunityId();
  return useQuery<CollectionRead>({
    queryKey: getReadCollectionQueryKey(communityId, collectionId ?? 0),
    queryFn: () => readCollection(communityId, collectionId ?? 0),
    enabled: collectionId !== null && Number.isFinite(collectionId),
  });
};

/** The filters a collection's file list takes, without the page. */
export type CollectionFilesParams = Omit<ListCollectionFilesParams, "page" | "page_size">;

/**
 * A collection's files, page by page, as somebody scrolls the wall.
 *
 * An infinite query rather than a page in the URL: a wall is scrolled, not
 * paged through, and what a page bounds is how much is fetched ahead of the
 * reader. `keepPreviousData` keeps the wall on screen while a changed filter
 * loads rather than blanking it.
 */
export const useCollectionFilesFeed = (
  collectionId: number | null,
  params?: CollectionFilesParams
) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    queryKey: getListCollectionFilesQueryKey(communityId, collectionId ?? 0, params),
    queryFn: ({ pageParam }) =>
      listCollectionFiles(communityId, collectionId ?? 0, {
        ...params,
        page: pageParam as number,
        page_size: PAGE_SIZE,
      }),
    initialPageParam: 1,
    getNextPageParam: (last: CollectionFileListResponse) =>
      last.has_next ? last.page + 1 : undefined,
    placeholderData: keepPreviousData,
    enabled: collectionId !== null && Number.isFinite(collectionId),
  });
};

/**
 * The months files were added to a collection in — what the timeline rail is
 * drawn from. Takes the list's filters, without its anchor: the rail is the
 * map, whichever month the list was jumped to.
 */
export const useCollectionFilesTimeline = (
  collectionId: number | null,
  params?: GetCollectionFilesTimelineParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const communityId = useActiveCommunityId();
  const { enabled = true, ...rest } = options ?? {};
  return useQuery<TimelineResponse>({
    queryKey: getGetCollectionFilesTimelineQueryKey(communityId, collectionId ?? 0, params),
    queryFn: () => getCollectionFilesTimeline(communityId, collectionId ?? 0, params),
    enabled: collectionId !== null && Number.isFinite(collectionId) && enabled,
    ...rest,
  });
};

const metadataSaves = new Map<number, FieldSaveKind<{ properties: PropertySummary[] }, never>>();

/**
 * How a file's values of a collection's metadata are saved, one at a time:
 * they are the collection's, so whoever may change it sets them, and its
 * lists and the file's own read show them.
 */
export const collectionMetadataSaves = (collectionId: number) => {
  let kind = metadataSaves.get(collectionId);
  if (!kind) {
    const name = `collection-metadata-${collectionId}`;
    kind = {
      name,
      readKey: (communityId, id) => heldKey(name, communityId, id),
      patch: () => Promise.reject(new Error("a file's collection metadata takes no patch")),
      properties: PropertyTarget.file,
      setProperties: (communityId, fileId, body) =>
        setCollectionFileMetadata(communityId, collectionId, fileId, body),
      lists: () => q.allCollections(),
      itself: (fileId) => q.file(fileId),
    };
    metadataSaves.set(collectionId, kind);
  }
  return kind;
};

/** Make a collection of the files named: a collection never starts empty. */
export const useCreateCollection = (options?: MutationOpts<CollectionRead, CollectionCreate>) =>
  useCommunityMutation<CollectionRead, CollectionCreate>(
    {
      mutationFn: (communityId, body) => createCollection(communityId, body),
      invalidate: invalidateCollectionContents,
      errorKey: "files:collections.error",
    },
    options
  );

export const useUpdateCollection = (
  collectionId: number,
  options?: MutationOpts<CollectionRead, CollectionUpdate>
) =>
  useCommunityMutation<CollectionRead, CollectionUpdate>(
    {
      mutationFn: (communityId, body) => updateCollection(communityId, collectionId, body),
      invalidate: () => invalidate(q.allCollections()),
      errorKey: "files:collections.error",
    },
    options
  );

/** Send a collection to the trash. Its files stay where they are. */
export const useDeleteCollection = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, collectionId) => deleteCollection(communityId, collectionId),
      invalidate: invalidateCollectionContents,
      errorKey: "files:collections.error",
    },
    options
  );

/** Files to put in a collection, and the values of its metadata each starts
 *  with: what its file page requires. */
export interface FilesToAdd {
  fileIds: number[];
  metadata?: PropertyValueInput[];
}

/** Put files in a collection. One already in it stays as it is. */
export const useAddCollectionFiles = (
  collectionId: number,
  options?: MutationOpts<CollectionRead, FilesToAdd>
) =>
  useCommunityMutation<CollectionRead, FilesToAdd>(
    {
      mutationFn: (communityId, { fileIds, metadata }) =>
        addCollectionFiles(communityId, collectionId, { file_ids: fileIds, metadata }),
      invalidate: invalidateCollectionContents,
      errorKey: "files:collections.error",
    },
    options
  );

/** Take files out of a collection. The files stay where they are, and a
 *  collection left with none goes to the trash. */
export const useRemoveCollectionFiles = (
  collectionId: number,
  options?: MutationOpts<void, number[]>
) =>
  useCommunityMutation<void, number[]>(
    {
      mutationFn: (communityId, fileIds) =>
        removeCollectionFiles(communityId, collectionId, { file_ids: fileIds }),
      invalidate: invalidateCollectionContents,
      errorKey: "files:collections.error",
    },
    options
  );

/** A file to upload into a collection, with the values of its metadata it
 *  starts with there. */
export interface FileToUpload {
  file: File;
  metadata?: PropertyValueInput[];
}

/**
 * Upload one file into the collection's initiative and put it in the
 * collection. One pair of requests per file — a drop of forty is forty of
 * these, run a few at a time by the uploader, so one failure does not take the
 * rest with it.
 *
 * Deliberately invalidates nothing and toasts nothing: the uploader refreshes
 * the wall a few times over a drop rather than once per file, and reports
 * failures per file.
 */
export const useUploadToCollection = (
  collection: Pick<CollectionRead, "id" | "initiative_id"> | undefined,
  options?: MutationOpts<FileRead, FileToUpload>
) =>
  useCommunityMutation<FileRead, FileToUpload>(
    {
      mutationFn: async (communityId, { file, metadata }) => {
        if (!collection) throw new Error("no collection to upload into");
        const uploaded = await uploadFile(communityId, {
          file,
          name: nameWithoutExtension(file.name),
          initiative_id: collection.initiative_id,
        });
        await addCollectionFiles(communityId, collection.id, {
          file_ids: [uploaded.id],
          metadata,
        });
        return uploaded;
      },
    },
    options
  );
