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

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { taskDetails, taskPresets } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { taskLists } from "@/components/layouts/taskLists";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useProject, useProjectTaskStatuses, useProjectTaskTypes } from "@/hooks/useProjects";
import { useProperties } from "@/hooks/useProperties";
import { useRouteId } from "@/hooks/useRouteId";
import { instanceTarget, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolSettingsRoute } from "@/lib/tools";

export const ProjectLayoutEditorPage = () => {
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const id = useRouteId("projectId");
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const types = useProjectTaskTypes(id).data;
  const properties = useProperties({
    owner: id === null ? undefined : { kind: "project", id },
    enabled: id !== null,
  }).data;
  const set = useInstanceLayouts(Tool.project, id).data;
  const editing = useMemo(
    () =>
      project && statuses && types && properties
        ? { id: project.id, initiativeId: project.initiative_id, properties, statuses, types }
        : null,
    [project, statuses, types, properties]
  );
  const lists = useMemo(() => (editing ? taskLists(editing) : null), [editing]);
  const details = useMemo(() => (editing ? taskDetails(editing) : []), [editing]);
  const presets = useMemo(() => (editing ? taskPresets(editing) : null), [editing]);

  if (!project || !set || !lists || !presets) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="tool" />;
  return (
    <LayoutEditor
      // Another project's editor starts afresh: a draft, and the question
      // before leaving it, belong to the project they were made for.
      key={project.id}
      target={instanceTarget(Tool.project, project.id)}
      initiativeId={project.initiative_id}
      lists={lists}
      presets={presets}
      details={details}
      set={set}
      initialKind={layout}
      ownPropertiesEditable={project.can.edit}
      onClose={() =>
        void navigate({
          to: gp(`${toolSettingsRoute(Tool.project, project.initiative_id, project.id)}/layouts`),
        })
      }
    />
  );
};
