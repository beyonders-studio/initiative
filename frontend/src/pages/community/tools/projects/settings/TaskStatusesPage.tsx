/**
 * `/settings/task-statuses` — the columns this project's tasks move through.
 */

import { useProject } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";
import { ProjectTaskStatusesManager } from "@/pages/community/tools/projects/settings/ProjectTaskStatusesManager";

export const TaskStatusesPage = () => {
  const project = useProject(useRouteId("projectId")).data;

  if (!project) return null;

  return <ProjectTaskStatusesManager projectId={project.id} canManage={project.can.edit} />;
};
