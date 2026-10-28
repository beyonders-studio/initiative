/**
 * `/projects/$projectId/layouts` — the project's layouts (its table, board and
 * calendar, and each task type's page), edited in place. `?layout=task:<id>`
 * opens on one type's page.
 *
 * Who may is the server's answer on the set (the project's owner, the
 * initiative's managers, a community admin). The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { taskDetails, taskPresets } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { useProject, useProjectTaskStatuses, useProjectTaskTypes } from "@/hooks/useProjects";
import { instanceTarget, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolSettingsRoute } from "@/lib/tools";

export const ProjectLayoutEditorPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const { layout } = useSearch({ strict: false }) as { layout?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const project = useProject(id).data;
  const statuses = useProjectTaskStatuses(id).data;
  const types = useProjectTaskTypes(id).data;
  const set = useInstanceLayouts(Tool.project, id).data;
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
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;
  return (
    <LayoutEditor
      // Another project's editor starts afresh: a draft, and the question
      // before leaving it, belong to the project they were made for.
      key={project.id}
      target={instanceTarget(Tool.project, project.id)}
      initiativeId={project.initiative_id}
      project={editing}
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
