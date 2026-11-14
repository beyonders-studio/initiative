import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useProject } from "@/hooks/useProjects";
import { useProjectTaskExportView } from "@/hooks/useProjectTaskView";
import { useRouteId } from "@/hooks/useRouteId";
import { ProjectDetailsFields } from "@/pages/community/tools/projects/settings/ProjectDetailsFields";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

/**
 * Layout for one project's settings: the header, the tab bar, and whichever
 * section the address names. Each section is a route of its own beneath this
 * one, so `/settings/task-statuses` can be linked to and bookmarked.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings"
)({
  component: ProjectSettings,
});

function ProjectSettings() {
  const { t } = useTranslation("projects");
  const projectId = useRouteId("projectId");
  const project = useProject(projectId).data;
  // An export from here lists the tasks this person's view of the project
  // does. Its reads wait for a finite id, so an address naming no project
  // reads nothing.
  const exportContent = useProjectTaskExportView(projectId ?? Number.NaN);

  return (
    <SettingsLayout
      tool={Tool.project}
      detailsInline={project && <ProjectDetailsFields project={project} />}
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
}
