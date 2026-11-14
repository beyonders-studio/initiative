/**
 * `/settings/properties` — what this project's tasks can hold beside the
 * initiative's metadata: the project's properties, made, renamed, reordered
 * and deleted by whoever may change the project's tasks.
 */

import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/InitiativeSettingsPropertiesTab";
import { useProject } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";

export const PropertiesPage = () => {
  const project = useProject(useRouteId("projectId")).data;

  if (!project) return null;

  return (
    <InitiativeSettingsPropertiesTab
      initiativeId={project.initiative_id}
      owner={{ kind: "project", id: project.id }}
      canManage={project.can.edit}
    />
  );
};
