import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { type ProjectRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getReadProjectQueryKey, readProject } from "@/api/generated/projects/projects";
import {
  getListTaskStatusesQueryKey,
  listTaskStatuses,
} from "@/api/generated/task-statuses/task-statuses";
import { keptView } from "@/hooks/useListView";
import { projectViewSpec, resolveProjectView } from "@/hooks/useProjectTaskView";
import { tasksQuery } from "@/hooks/useTasks";
import { instanceTarget, listLayouts, toolLayoutsQuery } from "@/hooks/useToolLayouts";
import { parseListLayout, parsePreset } from "@/lib/filters/layoutSearch";
import { buildTaskListParams } from "@/lib/filters/taskFilters";
import { viewPreferencesQuery } from "@/lib/viewPreferences";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/"
)({
  validateSearch: (search: Record<string, unknown>) => ({
    create: typeof search.create === "string" ? search.create : undefined,
    // Which of the project's list layouts it shows, which makes it linkable.
    layout: parseListLayout(search.layout),
    // A preset of that layout to start from, while nothing else is changed.
    preset: parsePreset(search.preset),
  }),
  // The prefetch depends on the search params, so the loader has to see them.
  loaderDeps: ({ search }) => search,
  loader: ({ context, params, deps }) => {
    const projectId = Number(params.projectId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void (async () => {
      try {
        const [, set, views] = await Promise.all([
          queryClient.ensureQueryData<ProjectRead>({
            queryKey: getReadProjectQueryKey(communityId, projectId),
            queryFn: () => readProject(communityId, projectId),
            staleTime: 30_000,
          }),
          queryClient.ensureQueryData({
            ...toolLayoutsQuery(communityId, instanceTarget(Tool.project, projectId)),
            staleTime: 60_000,
          }),
          queryClient.ensureQueryData(viewPreferencesQuery(communityId)),
          queryClient.ensureQueryData({
            queryKey: getListTaskStatusesQueryKey(communityId, projectId),
            queryFn: () => listTaskStatuses(communityId, projectId),
            staleTime: 60_000,
          }),
        ]);

        // Resolve exactly the way the section does, and build the params with the
        // same function, so the prefetch lands on the key the component asks for.
        // These used to be two separate implementations that had drifted, and the
        // prefetched entry was never read.
        const { spec } = resolveProjectView(
          deps,
          listLayouts(set),
          keptView(views.items, projectViewSpec(communityId, projectId)).view
        );
        const taskParams = buildTaskListParams(spec, { projectId });

        // Deliberately not awaited: re-running the loader on a layout change must
        // not block the navigation on a task refetch.
        void queryClient.ensureQueryData({
          ...tasksQuery(communityId, taskParams),
          staleTime: 30_000,
        });
      } catch {
        // Silently fail - component will fetch its own data
      }
    })();
  },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectDetailPage").then((m) => ({
      default: m.ProjectDetailPage,
    }))
  ),
});
