import { createFileRoute } from "@tanstack/react-router";

import { getReadProjectQueryOptions } from "@/api/generated/projects/projects";
import { getListTaskStatusesQueryOptions } from "@/api/generated/task-statuses/task-statuses";
import { getReadTaskQueryOptions } from "@/api/generated/tasks/tasks";
import { commentThreadQueryOptions } from "@/hooks/useComments";
import { TaskPage } from "@/pages/community/tools/projects/task/TaskPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/tasks/$taskId"
)({
  loader: ({ context, params }) => {
    const taskId = Number(params.taskId);
    const projectId = Number(params.projectId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    // The project comes from the path, so all four reads start together
    // instead of waiting on the task to name its project.
    void Promise.all([
      queryClient.ensureQueryData(getReadTaskQueryOptions(communityId, taskId)),
      queryClient.ensureInfiniteQueryData({
        ...commentThreadQueryOptions(communityId, { task_id: taskId }),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData(getReadProjectQueryOptions(communityId, projectId)),
      queryClient.ensureQueryData(
        getListTaskStatusesQueryOptions(communityId, projectId, { query: { staleTime: 60_000 } })
      ),
    ]).catch(() => {});
  },
  component: TaskPage,
});
