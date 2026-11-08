/**
 * `/<tool>/$id/layouts` — how a tool's items are shown when one is opened (a
 * counter group's counters), laid out in place.
 *
 * Who may is the server's answer on the set (the tool's owner, the
 * initiative's managers, a community admin). The editor itself says when the
 * screen is too narrow to edit on, and keeps its draft while it is.
 */

import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ITEM_DETAILS } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useRouteId } from "@/hooks/useRouteId";
import { instanceTarget, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolCamelSingular, toolSettingsSectionRoute } from "@/lib/tools";

export const ItemLayoutEditorPage = ({ tool }: { tool: Tool }) => {
  const id = useRouteId(`${toolCamelSingular(tool)}Id`);
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const entity = TOOL_HOOKS[tool].useDetail(id).data;
  // A community's own tool belongs to no initiative, and has no layouts.
  const initiativeId = entity?.initiative_id ?? null;
  const set = useInstanceLayouts(tool, id).data;
  const detail = ITEM_DETAILS[tool];
  const details = useMemo(
    () => (initiativeId !== null && id !== null && detail ? [detail(id, initiativeId)] : []),
    [initiativeId, id, detail]
  );

  if (!set || id === null || initiativeId === null) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="tool" />;
  return (
    <LayoutEditor
      // Another instance's editor starts afresh: a draft, and the question
      // before leaving it, belong to the one they were made for.
      key={id}
      target={instanceTarget(tool, id)}
      initiativeId={initiativeId}
      details={details}
      set={set}
      onClose={() =>
        void navigate({
          to: gp(toolSettingsSectionRoute(tool, initiativeId, id, "layouts")),
        })
      }
    />
  );
};
