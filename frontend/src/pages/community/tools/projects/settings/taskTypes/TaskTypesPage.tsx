/**
 * `/settings/task-types` — the kinds of task this project holds, and the way
 * into each one's page.
 */

import { useProject } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";

import { ProjectTaskTypesManager } from "./ProjectTaskTypesManager";

export const TaskTypesPage = () => {
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
