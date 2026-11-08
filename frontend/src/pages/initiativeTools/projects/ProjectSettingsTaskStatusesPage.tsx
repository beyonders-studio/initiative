/**
 * `/settings/task-statuses` — the columns this project's tasks move through.
 */

import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { useProject } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";

export const ProjectSettingsTaskStatusesPage = () => {
  const project = useProject(useRouteId("projectId")).data;

  if (!project) return null;

  return <ProjectTaskStatusesManager projectId={project.id} canManage={project.can.edit} />;
};
