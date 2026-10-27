import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  createFile,
  deleteFileVersion,
  duplicateFile,
  getListFilesQueryKey,
  getListFileVersionsQueryKey,
  getReadFileQueryKey,
  listFiles,
  listFileVersions,
  putVideoThumbnail,
  setFileGrants,
  uploadFile,
  uploadFileVersion,
} from "@/api/generated/files/files";
import type {
  FileCreate,
  FileListResponse,
  FileRead,
  FileVersionRead,
  ListFilesParams,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { relate } from "@/api/relationships";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { getErrorMessage } from "@/lib/errorMessage";
import type { EditorFileType } from "@/lib/fileTypes";
import { toast } from "@/lib/mascotToast";
import { type ResumableOptions, uploadInPieces } from "@/lib/resumableUpload";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard hooks ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires. A file's create is
// its own, and is written out below.

const files = TOOL_HOOKS[Tool.file];
export const useFilesList = files.useList;
export const useFile = files.useDetail;
export const useUpdateFile = files.useUpdate;
/**
 * Single-file delete — the shape every tool's delete hook takes, so the
 * shared settings page needs no per-tool adapter.
 */
export const useDeleteFile = files.useDelete;
export const useSetFileGrants = files.useSetGrants;

const FEED_PAGE_SIZE = 60;

/**
 * Files page by page, as somebody scrolls a grid of them — the image
 * chooser's pictures. `keepPreviousData` keeps the grid on screen while a
 * changed filter loads rather than blanking it.
 */
export const useFilesFeed = (
  params: Omit<ListFilesParams, "page" | "page_size">,
  options?: { enabled?: boolean }
) => {
  const communityId = useActiveCommunityId();
  return useInfiniteQuery({
    // Its own key beside the list's: pages of the feed are a different shape.
    queryKey: [...getListFilesQueryKey(communityId, params), "feed"],
    queryFn: ({ pageParam }) =>
      listFiles(communityId, { ...params, page: pageParam, page_size: FEED_PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (last: FileListResponse) => (last.has_next ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
    enabled: options?.enabled ?? true,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

export const useSetFileCache = () => {
  const qc = useQueryClient();
  const communityId = useActiveCommunityId();
  return (
    fileId: number,
    data: FileRead | ((prev: FileRead | undefined) => FileRead | undefined)
  ) => {
    qc.setQueryData<FileRead>(
      getReadFileQueryKey(communityId, fileId),
      typeof data === "function" ? data : () => data
    );
  };
};

// ── Mutations ───────────────────────────────────────────────────────────────

// Helper: apply a file's full sharing state via a follow-up grants PUT (for
// copy/upload paths where the create payload can't carry them). Returns 1 if the
// call failed, else 0.
const applyFileGrants = async (
  communityId: number,
  fileId: number,
  grants: ResourceGrantSchema[]
): Promise<number> => {
  if (grants.length === 0) return 0;
  try {
    await setFileGrants(communityId, fileId, grants);
    return 0;
  } catch {
    return 1;
  }
};

type CreateFileInput = {
  name: string;
  initiative_id: number;
  is_template?: boolean;
  template_id?: number;
  project_id?: number;
  /** Omit for a text file; uploads go through useUploadFile instead. */
  file_type?: EditorFileType;
  /** Required for a link ({ url: "..." }). Optional/unused for other types. */
  content?: Record<string, unknown>;
  /** Full non-owner sharing state for the new file. */
  grants?: ResourceGrantSchema[];
};

export const useCreateFile = (options?: MutationOpts<FileRead, CreateFileInput>) => {
  const { t } = useTranslation("files");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: CreateFileInput) => {
      const {
        name,
        initiative_id,
        is_template,
        template_id,
        project_id,
        file_type,
        content,
        grants = [],
      } = data;

      let newFile: FileRead;

      if (template_id) {
        // Copy from template
        newFile = await duplicateFile(communityId, template_id, {
          target_initiative_id: initiative_id,
          name,
        });
        // Template copy can't carry grants in payload — apply separately
        const failures = await applyFileGrants(communityId, newFile.id, grants);
        if (failures > 0) {
          toast.warning(t("create.somePermissionsFailed"));
        }
      } else {
        // Direct create — pass grants in the payload (backend handles them)
        const payload: FileCreate = {
          name,
          initiative_id,
          is_template: is_template ?? false,
          ...(file_type ? { file_type } : {}),
          ...(content ? { content } : {}),
          ...(grants.length > 0 ? { grants } : {}),
        };
        newFile = await createFile(communityId, payload);
      }

      // Auto-attach to project if specified
      if (project_id) {
        await relate(
          communityId,
          { type: SearchEntityType.project, id: project_id },
          { type: SearchEntityType.file, id: newFile.id }
        );
      }

      return newFile;
    },
    onSuccess: (...args) => {
      void invalidate(q.allFiles());
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidate(q.project(projectId));
      }
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "files:create.createError"));
      onError?.(...args);
    },
    onSettled,
  });
};

type UploadFileInput = {
  file: Blob;
  name: string;
  initiative_id: number;
  project_id?: number;
  /** Full non-owner sharing state for the uploaded file. */
  grants?: ResourceGrantSchema[];
} & ResumableOptions;

export const useUploadFile = (options?: MutationOpts<FileRead, UploadFileInput>) => {
  const { t } = useTranslation("files");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (data: UploadFileInput) => {
      const { file, name, initiative_id, project_id, grants = [], ...sending } = data;

      const newFile = await uploadInPieces(
        communityId,
        file,
        file instanceof File ? file.name : name,
        { purpose: "file", initiativeId: initiative_id },
        (upload_id) => uploadFile(communityId, { name, initiative_id, upload_id }),
        sending
      );

      // Upload can't carry grants in payload — apply separately
      const failures = await applyFileGrants(communityId, newFile.id, grants);
      if (failures > 0) {
        toast.warning(t("create.somePermissionsFailed"));
      }

      // Auto-attach to project if specified
      if (project_id) {
        await relate(
          communityId,
          { type: SearchEntityType.project, id: project_id },
          { type: SearchEntityType.file, id: newFile.id }
        );
      }

      return newFile;
    },
    onSuccess: (...args) => {
      void invalidate(q.allFiles());
      const projectId = args[1].project_id;
      if (projectId) {
        void invalidate(q.project(projectId));
      }
      onSuccess?.(...args);
    },
    onError: (...args) => {
      // Stopped on purpose: nothing went wrong.
      if (!args[1].signal?.aborted)
        toast.error(getErrorMessage(args[0], "files:create.uploadError"));
      onError?.(...args);
    },
    onSettled,
  });
};

// ── File versions ─────────────────────────────────────────────────────────

export const useFileVersions = (fileId: number | null, options?: QueryOpts<FileVersionRead[]>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<FileVersionRead[]>({
    queryKey: getListFileVersionsQueryKey(communityId, fileId!),
    queryFn: () => listFileVersions(communityId, fileId!),
    enabled: fileId !== null && Number.isFinite(fileId) && userEnabled,
    ...rest,
  });
};

type UploadFileVersionInput = { fileId: number; file: Blob } & ResumableOptions;

export const useUploadFileVersion = (
  options?: MutationOpts<FileVersionRead, UploadFileVersionInput>
) => {
  const { t } = useTranslation("files");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: ({ fileId, file, ...sending }: UploadFileVersionInput) =>
      uploadInPieces(
        communityId,
        file,
        file instanceof File ? file.name : "file",
        { purpose: "file", fileId },
        (upload_id) => uploadFileVersion(communityId, fileId, { upload_id }),
        sending
      ),
    onSuccess: (...args) => {
      const fileId = args[1].fileId;
      void invalidate(q.fileVersions(fileId));
      // Mirror file fields on the file row changed — refresh detail + lists.
      void invalidate(q.file(fileId), q.allFiles());
      toast.success(t("versions.uploadSuccess"));
      onSuccess?.(...args);
    },
    onError: (...args) => {
      // Stopped on purpose: nothing went wrong.
      if (!args[1].signal?.aborted)
        toast.error(getErrorMessage(args[0], "files:versions.uploadError"));
      onError?.(...args);
    },
    onSettled,
  });
};

/** Give a video version the frame the browser drew of it. Quiet: nobody asked
 *  for it, so a refusal (a frame another editor sent first) says nothing. */
export const usePutVideoThumbnail = () => {
  const communityId = useActiveCommunityId();
  return useMutation({
    mutationFn: ({
      fileId,
      versionId,
      frame,
    }: {
      fileId: number;
      versionId: number;
      frame: Blob;
    }) => putVideoThumbnail(communityId, fileId, versionId, { file: frame }),
    onSuccess: (_reply, { fileId }) => {
      void invalidate(q.file(fileId), q.allFiles());
    },
  });
};

export const useDeleteFileVersion = (
  options?: MutationOpts<void, { fileId: number; versionId: number }>
) => {
  const { t } = useTranslation("files");
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ fileId, versionId }: { fileId: number; versionId: number }) => {
      await deleteFileVersion(communityId, fileId, versionId);
    },
    onSuccess: (...args) => {
      const fileId = args[1].fileId;
      void invalidate(q.fileVersions(fileId), q.file(fileId), q.allFiles());
      toast.success(t("versions.deleteSuccess"));
      onSuccess?.(...args);
    },
    onError: (...args) => {
      toast.error(getErrorMessage(args[0], "files:versions.deleteError"));
      onError?.(...args);
    },
    onSettled,
  });
};
