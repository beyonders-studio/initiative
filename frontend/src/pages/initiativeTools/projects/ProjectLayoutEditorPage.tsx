/**
 * `/projects/$projectId/layouts` — the project's layouts (its table, board and
 * calendar, and each task type's page), edited in place. `?layout=task:<id>`
 * opens on one type's page.
 *
 * Who may is the server's answer on the set (the project's owner, the
 * initiative's managers, a community admin). The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPropertiesTab } from "@/components/initiatives/settings/InitiativeSettingsPropertiesTab";
import { taskDetails, taskPresets } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { useProject, useProjectTaskStatuses, useProjectTaskTypes } from "@/hooks/useProjects";
import { useRouteId } from "@/hooks/useRouteId";
import { instanceTarget, useInstanceLayouts, useSaveLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { useLayoutPlugins } from "@/lib/layouts/plugins";
import { initiativeRoute, toolSettingsRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

export const ProjectLayoutEditorPage = () => {
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const id = useRouteId("projectId");
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const { t } = useTranslation(LAYOUT_NAMESPACES);

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const types = useProjectTaskTypes(id).data;
  const set = useInstanceLayouts(Tool.project, id).data;
  const save = useSaveLayouts(instanceTarget(Tool.project, id ?? 0));
  const plugins = useLayoutPlugins(project?.initiative_id, "task");
  const editing = useMemo(
    () =>
      project && statuses && types
        ? { id: project.id, initiativeId: project.initiative_id, statuses, types }
        : null,
    [project, statuses, types]
  );
  const details = useMemo(() => (editing ? taskDetails(editing) : []), [editing]);
  const presets = useMemo(() => (editing ? taskPresets(editing) : null), [editing]);

  if (!project || !editing || !set || !presets) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="tool" />;
  return (
    <LayoutEditor
      // Another project's editor starts afresh: a draft, and the question
      // before leaving it, belong to the project they were made for.
      key={project.id}
      t={t as TranslateFn}
      initiativeId={project.initiative_id}
      project={editing}
      presets={presets}
      details={details}
      plugins={plugins}
      layouts={set}
      save={save.mutateAsync}
      initialKind={layout}
      properties={(placement) => (
        <InitiativeSettingsPropertiesTab
          initiativeId={project.initiative_id}
          owner={{ kind: "project", id: project.id }}
          canManage={project.can.edit}
          placement={placement}
        />
      )}
      metadataHref={gp(`${initiativeRoute(project.initiative_id)}/settings/properties`)}
      onClose={() =>
        void navigate({
          to: gp(`${toolSettingsRoute(Tool.project, project.initiative_id, project.id)}/layouts`),
        })
      }
    />
  );
};
