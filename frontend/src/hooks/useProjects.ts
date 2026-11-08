import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  ListMyProjectsParams,
  ListProjectsParams,
  ProjectListResponse,
  ProjectRead,
  TaskStatusCreate,
  TaskStatusDeleteRequest,
  TaskStatusRead,
  TaskStatusReorderRequest,
  TaskStatusUpdate,
  TaskTypeCopyRequest,
  TaskTypeCreate,
  TaskTypeCreated,
  TaskTypeDeleteRequest,
  TaskTypeGalleryGroup,
  TaskTypeRead,
  TaskTypeReorderRequest,
  TaskTypeUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { getGetLayoutsQueryKey, putLayout } from "@/api/generated/layouts/layouts";
import {
  getListProjectsQueryKey,
  getReadProjectQueryKey,
  listProjects,
  reorderProjects,
  updateProject,
} from "@/api/generated/projects/projects";
import {
  createTaskStatus,
  deleteTaskStatus,
  getListTaskStatusesQueryKey,
  listTaskStatuses,
  reorderTaskStatuses,
  updateTaskStatus,
} from "@/api/generated/task-statuses/task-statuses";
import {
  copyTaskTypes,
  createTaskType,
  deleteTaskType,
  getListTaskTypeGalleryQueryKey,
  getListTaskTypesQueryKey,
  listTaskTypeGallery,
  listTaskTypes,
  reorderTaskTypes,
  updateTaskType,
} from "@/api/generated/task-types/task-types";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { instanceTarget } from "@/hooks/useToolLayouts";
import { fetchAllPages } from "@/lib/fetchAllPages";
import { taskPageWithFields } from "@/lib/layouts/tasks";
import { toolViewParams } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── The standard six ────────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const projects = TOOL_HOOKS[Tool.project];
export const useProjects = projects.useList;
export const useProject = projects.useDetail;
export const useUpdateProject = projects.useUpdate;
export const useCreateProject = projects.useCreate;
export const useDeleteProject = projects.useDelete;
export const useSetProjectGrants = projects.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/** Templates across every initiative the caller can see — the create dialog's
 *  "start from a template" picker, read once the dialog is open. */
export const useTemplateProjects = (open: boolean) =>
  useProjects({ is_template: true }, { enabled: open });

/** Every live project `filters` match, every window of the list read — for a
 *  picker that has to offer all of them rather than the first page. */
export const useAllProjects = (
  filters: ListProjectsParams = {},
  options?: QueryOpts<ProjectListResponse>
) => {
  const communityId = useActiveCommunityId();
  const params = {
    slim: true,
    page_size: 0,
    ...toolViewParams(Tool.project, "active"),
    ...filters,
  };
  return useQuery<ProjectListResponse>({
    queryKey: getListProjectsQueryKey(communityId, params),
    queryFn: () => fetchAllPages((p) => listProjects(communityId, p), params),
    staleTime: 60 * 1000,
    ...options,
  });
};

/** Every live project the reader may edit — where a task can be moved to; a
 *  template takes no tasks moved into it. */
export const useWritableProjects = (options?: QueryOpts<ProjectListResponse>) =>
  useAllProjects({ writable: true }, options);

export const useProjectTaskStatuses = (
  projectId: number | null,
  options?: QueryOpts<TaskStatusRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskStatusRead[]>({
    queryKey: getListTaskStatusesQueryKey(communityId, projectId!),
    queryFn: () => listTaskStatuses(communityId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

/** The task types of each of these projects, in their order: what a filter
 *  across several projects picks from. Shares each project's own read. */
export const useTaskTypesOf = (projectIds: readonly number[]) => {
  const communityId = useActiveCommunityId();
  return useQueries({
    queries: projectIds.map((projectId) => ({
      queryKey: getListTaskTypesQueryKey(communityId, projectId),
      queryFn: () => listTaskTypes(communityId, projectId),
    })),
  });
};

/** The ready-made types a project can add, grouped, in the reader's
 *  language, read again when it changes. */
export const useTaskTypeGallery = (
  projectId: number,
  options?: QueryOpts<TaskTypeGalleryGroup[]>
) => {
  const communityId = useActiveCommunityId();
  const { i18n } = useTranslation();
  return useQuery<TaskTypeGalleryGroup[]>({
    queryKey: [...getListTaskTypeGalleryQueryKey(communityId, projectId), i18n.language],
    queryFn: () => listTaskTypeGallery(communityId, projectId),
    staleTime: Number.POSITIVE_INFINITY,
    ...options,
  });
};

/** A project's task types, in order. */
export const useProjectTaskTypes = (
  projectId: number | null,
  options?: QueryOpts<TaskTypeRead[]>
) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<TaskTypeRead[]>({
    queryKey: getListTaskTypesQueryKey(communityId, projectId!),
    queryFn: () => listTaskTypes(communityId, projectId!),
    enabled: projectId !== null && Number.isFinite(projectId) && userEnabled,
    ...rest,
  });
};

// ── Global (cross-community) queries ────────────────────────────────────────────

export const useGlobalProjects = (
  params?: ListMyProjectsParams,
  options?: QueryOpts<ProjectListResponse>
) => {
  return useQuery<ProjectListResponse>({
    ...projects.myListQuery(params),
    ...options,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useReorderProjects = (options?: MutationOpts<void, number[]>) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async (orderedIds: number[]) => {
      await reorderProjects(communityId, { project_ids: orderedIds });
    },
    onSuccess,
    onError,
    onSettled: (...args) => {
      void invalidate(q.allProjects());
      onSettled?.(...args);
    },
  });
};

// ── Pin Mutations ────────────────────────────────────────────────────────────

interface TogglePinArgs {
  projectId: number;
  nextState: boolean;
}

const replaceProjectInList = (
  prev: ProjectListResponse | undefined,
  updated: ProjectRead
): ProjectListResponse | undefined => {
  if (!prev) return prev;
  return {
    ...prev,
    items: prev.items.map((project) => (project.id === updated.id ? updated : project)),
  };
};

export const useToggleProjectPin = (options?: MutationOpts<ProjectRead, TogglePinArgs>) => {
  const communityId = useActiveCommunityId();
  const qc = useQueryClient();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation({
    ...rest,
    mutationFn: async ({ projectId, nextState }: TogglePinArgs) => {
      return updateProject(communityId, projectId, {
        pinned: nextState,
      });
    },
    onSuccess: (...args) => {
      const data = args[0];
      // Every cached project list, whatever it was narrowed by — the keys carry
      // an initiative and a page, so naming them one by one silently misses the
      // list the reader is actually looking at.
      qc.setQueriesData<ProjectListResponse>(
        { queryKey: getListProjectsQueryKey(communityId) },
        (prev) => replaceProjectInList(prev, data)
      );
      qc.setQueryData<ProjectRead>(getReadProjectQueryKey(communityId, data.id), () => data);
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};

// ── Task Status Mutations ───────────────────────────────────────────────────

const invalidateStatusesAndTasks = (projectId: number) =>
  invalidate(q.projectTaskStatuses(projectId), q.allTasks());

export const useCreateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, TaskStatusCreate>
) =>
  useCommunityMutation<TaskStatusRead, TaskStatusCreate>(
    {
      mutationFn: (communityId, data) => createTaskStatus(communityId, projectId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useUpdateTaskStatus = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>
) =>
  useCommunityMutation<TaskStatusRead, { statusId: number; data: TaskStatusUpdate }>(
    {
      mutationFn: (communityId, { statusId, data }) =>
        updateTaskStatus(communityId, projectId, statusId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );

export const useDeleteTaskStatus = (
  projectId: number,
  options?: MutationOpts<void, { statusId: number; data: TaskStatusDeleteRequest }>
) =>
  useCommunityMutation<void, { statusId: number; data: TaskStatusDeleteRequest }>(
    {
      mutationFn: (communityId, { statusId, data }) =>
        deleteTaskStatus(communityId, projectId, statusId, data),
      invalidate: () => invalidateStatusesAndTasks(projectId),
    },
    options
  );

export const useReorderTaskStatuses = (
  projectId: number,
  options?: MutationOpts<TaskStatusRead[], TaskStatusReorderRequest>
) =>
  useCommunityMutation<TaskStatusRead[], TaskStatusReorderRequest>(
    {
      mutationFn: (communityId, data) => reorderTaskStatuses(communityId, projectId, data),
      invalidate: () => invalidate(q.projectTaskStatuses(projectId)),
    },
    options
  );

// ── Task Type Mutations ─────────────────────────────────────────────────────

/** A project's types are read twice: their own list, and on the project. */
const invalidateTaskTypes = (projectId: number, ...more: Spec[]) =>
  invalidate(q.projectTaskTypes(projectId), q.project(projectId), ...more);

/** Adding a type. One started from another gets a copy of that type's page,
 *  so the project's layouts read anew. */
export const useCreateTaskType = (
  projectId: number,
  options?: MutationOpts<TaskTypeCreated, TaskTypeCreate>
) =>
  useCommunityMutation<TaskTypeCreated, TaskTypeCreate>(
    {
      mutationFn: (communityId, data) => createTaskType(communityId, projectId, data),
      invalidate: () => invalidateTaskTypes(projectId, q.layouts()),
    },
    options
  );

/** Give a ready-made type's fields a place on its page: its shape's, with
 *  them at the end of the side's first section. Rejects when the page could
 *  not be saved; the type stands either way. */
export const usePlaceTaskTypeFields = (projectId: number) => {
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  return async (created: TaskTypeCreated) => {
    const target = instanceTarget(Tool.project, projectId);
    const set = await putLayout(
      communityId,
      {
        kind: "task",
        task_type_id: created.id,
        definition: taskPageWithFields(created.layout_preset, created.field_ids),
      },
      target
    );
    queryClient.setQueryData(getGetLayoutsQueryKey(communityId, target), set);
    void invalidate(q.initiativeLayouts());
  };
};

/** Copying types from another project, each with its page. */
export const useCopyTaskTypes = (
  projectId: number,
  options?: MutationOpts<TaskTypeRead[], TaskTypeCopyRequest>
) =>
  useCommunityMutation<TaskTypeRead[], TaskTypeCopyRequest>(
    {
      mutationFn: (communityId, data) => copyTaskTypes(communityId, projectId, data),
      invalidate: () => invalidateTaskTypes(projectId, q.layouts()),
    },
    options
  );

/** Changing a type. Every task of it carries its name, look and shape, so
 *  the tasks read anew too. */
export const useUpdateTaskType = (
  projectId: number,
  options?: MutationOpts<TaskTypeRead, { typeId: number; data: TaskTypeUpdate }>
) =>
  useCommunityMutation<TaskTypeRead, { typeId: number; data: TaskTypeUpdate }>(
    {
      mutationFn: (communityId, { typeId, data }) =>
        updateTaskType(communityId, projectId, typeId, data),
      invalidate: () => invalidateTaskTypes(projectId, q.allTasks()),
    },
    options
  );

/** Deleting a type moves its tasks to another and takes its page with it. */
export const useDeleteTaskType = (
  projectId: number,
  options?: MutationOpts<void, { typeId: number; data: TaskTypeDeleteRequest }>
) =>
  useCommunityMutation<void, { typeId: number; data: TaskTypeDeleteRequest }>(
    {
      mutationFn: (communityId, { typeId, data }) =>
        deleteTaskType(communityId, projectId, typeId, data),
      invalidate: () => invalidateTaskTypes(projectId, q.allTasks(), q.layouts()),
    },
    options
  );

export const useReorderTaskTypes = (
  projectId: number,
  options?: MutationOpts<TaskTypeRead[], TaskTypeReorderRequest>
) =>
  useCommunityMutation<TaskTypeRead[], TaskTypeReorderRequest>(
    {
      mutationFn: (communityId, data) => reorderTaskTypes(communityId, projectId, data),
      invalidate: () => invalidateTaskTypes(projectId),
    },
    options
  );
