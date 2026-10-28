/**
 * `/settings/metadata` — what this project's tasks can hold beside the
 * initiative's properties: its metadata, made, renamed, reordered and
 * deleted by whoever may change the project's tasks.
 */

import { useParams } from "@tanstack/react-router";

import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/settings/InitiativeSettingsPropertiesTab";
import { useProject } from "@/hooks/useProjects";

export const ProjectSettingsMetadataPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const projectQuery = useProject(isValidId ? parsedId : null);
  const project = projectQuery.data;

  if (!project) return null;

  return (
    <InitiativeSettingsPropertiesTab
      initiativeId={project.initiative_id}
      owner={{ kind: "project", id: project.id }}
      canManage={project.can.edit}
    />
  );
};
