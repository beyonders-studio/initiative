/**
 * `/settings/task-types` — the kinds of task this project holds, and the way
 * into each one's page.
 */

import { ProjectTaskTypesManager } from "@/components/projects/ProjectTaskTypesManager";
import { useProject } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";

export const ProjectSettingsTaskTypesPage = () => {
  const project = useProject(useRouteId("projectId")).data;

  if (!project) return null;

  return (
    <ProjectTaskTypesManager
      projectId={project.id}
      initiativeId={project.initiative_id}
      canManage={project.can.edit}
    />
  );
};
