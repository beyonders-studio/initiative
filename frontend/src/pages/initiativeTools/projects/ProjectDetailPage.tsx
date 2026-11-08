import { useRouter, useSearch } from "@tanstack/react-router";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ProjectHeader } from "@/components/projects/ProjectHeader";
import { ProjectRelationships } from "@/components/projects/ProjectRelationships";
import { ProjectTasksSection } from "@/components/projects/ProjectTasksSection";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { clearLastUsedProject } from "@/components/tasks/CreateTaskWizard";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useProject, useProjectTaskStatuses } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";
import { useCommunityPath } from "@/lib/communityUrl";
import { getHttpStatus } from "@/lib/errorMessage";
import { taskRoute, toolListRoute } from "@/lib/tools";
import { ProjectDetailSkeleton } from "@/ui/page-skeletons";
import { PullToRefresh } from "@/ui/pull-to-refresh";

export const ProjectDetailPage = () => {
  const { t } = useTranslation("projects");
  const projectId = useRouteId("projectId");
  const router = useRouter();
  const gp = useCommunityPath();
  const searchParams = useSearch({ strict: false }) as { create?: string };

  // Clear ?create from URL when the task composer closes
  const handleComposerOpenChange = useCallback(
    (isOpen: boolean) => {
      if (!isOpen && searchParams.create) {
        void router.navigate({
          to: ".",
          search: {},
          replace: true,
        });
      }
    },
    [searchParams.create, router]
  );

  const handleRefresh = useCallback(async () => {
    await invalidate(
      q.project(projectId ?? 0),
      q.allTasks(),
      q.projectTaskStatuses(projectId ?? 0),
      q.layouts()
    );
  }, [projectId]);

  const projectQuery = useProject(projectId);

  // Tasks query is now inside ProjectTasksSection to support server-side filtering

  const taskStatusesQuery = useProjectTaskStatuses(projectId);

  const viewedProjectId = projectQuery.data?.id;
  useReadOnOpen(Tool.project, viewedProjectId);
  useRecordOpen(Tool.project, viewedProjectId);

  const project = projectQuery.data;
  // Creating a file targets the project's initiative, so it follows that
  // initiative's server-computed create flag.
  const { canCreate: canCreateFiles } = useToolCreateAccess(Tool.file, {
    initiativeId: project?.initiative_id,
  });
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(project?.initiative_id);
  // Stable identity: the task table's column definitions and its memoized
  // cells both key off this. Declared with the other hooks, above the early
  // returns below.
  const taskHref = useCallback(
    (taskId: number) => gp(taskRoute(initiativeId, projectId ?? 0, taskId)),
    [gp, initiativeId, projectId]
  );

  if (projectQuery.isLoading || taskStatusesQuery.isLoading) {
    return <ProjectDetailSkeleton />;
  }

  if (projectQuery.isError || taskStatusesQuery.isError || !project) {
    const error = projectQuery.error ?? taskStatusesQuery.error;
    const status = getHttpStatus(error);
    if (projectId !== null && (status === 404 || status === 403)) {
      clearLastUsedProject(projectId);
    }
    return (
      <ToolAccessStatus
        error={error}
        keys="projects:detail."
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("detail.backToProjects")}
        entity={projectId === null ? undefined : { kind: "project", id: projectId }}
      />
    );
  }

  const canEdit = project.can.edit;
  const projectIsArchived = project.archived_at !== null;

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-4">
        <ProjectHeader project={project} projectIsArchived={projectIsArchived} />
        <ProjectRelationships
          projectId={project.id}
          projectName={project.name}
          initiativeId={project.initiative_id}
          canCreate={Boolean(canCreateFiles && !projectIsArchived)}
          canAttach={canEdit}
        />
        <ProjectTasksSection
          projectId={project.id}
          initiativeId={project.initiative_id}
          taskStatuses={taskStatusesQuery.data ?? []}
          canEditTaskDetails={canEdit}
          projectIsArchived={projectIsArchived}
          taskHref={taskHref}
          initialComposerOpen={searchParams.create === "true"}
          onComposerOpenChange={handleComposerOpenChange}
        />
        <ToolCommentsPanel tool={Tool.project} entity={project} />
      </div>
    </PullToRefresh>
  );
};
