import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ProjectDetailsFields } from "@/components/projects/settings/ProjectDetailsFields";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useDeleteProject,
  useProject,
  useSetProjectGrants,
  useUpdateProject,
} from "@/hooks/useProjects";
import { useProjectTaskExportView } from "@/hooks/useProjectTaskView";

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);
  const { t } = useTranslation("projects");

  const projectQuery = useProject(isValidId ? parsedId : null);
  const update = useUpdateProject(parsedId);
  const setGrants = useSetProjectGrants(parsedId);
  const remove = useDeleteProject();

  const project = projectQuery.data;
  // An export from here lists the tasks this person's view of the project does.
  const exportContent = useProjectTaskExportView(parsedId);

  return (
    <ToolSettingsLayout
      tool={Tool.project}
      entity={project}
      isLoading={isValidId && projectQuery.isLoading}
      isError={!isValidId || projectQuery.isError}
      update={update}
      template={update}
      setGrants={setGrants}
      remove={remove}
      detailsInline={project ? <ProjectDetailsFields project={project} /> : null}
      exportOptions={{ content: exportContent }}
      // Settings too large for a card. Each is served by its own route beside
      // the shared sections, so the value doubles as the URL segment.
      extraTabs={[
        { value: "task-statuses", label: t("settings.tabTaskStatuses") },
        { value: "task-types", label: t("settings.tabTaskTypes") },
        { value: "properties", label: t("settings.tabProperties") },
      ]}
    />
  );
};
