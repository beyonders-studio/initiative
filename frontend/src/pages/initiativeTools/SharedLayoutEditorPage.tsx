/**
 * `/<tool>/layouts` — the layouts of a tool the whole initiative shares (its
 * calendar's event detail and list, its notices' detail), laid out in place.
 *
 * Who may is the server's answer on the set (the initiative's managers, a
 * community admin). The editor itself says when the screen is too narrow to
 * edit on, and keeps its draft while it is.
 */

import { useNavigate, useParams } from "@tanstack/react-router";
import { useMemo } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SHARED_LAYOUTS } from "@/components/layouts/details";
import { LayoutEditor } from "@/components/layouts/LayoutEditor";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { sharedTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { initiativeRoute } from "@/lib/tools";

export const SharedLayoutEditorPage = ({ tool }: { tool: Tool }) => {
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const parsedId = initiativeId ? Number(initiativeId) : Number.NaN;
  const id = Number.isFinite(parsedId) ? parsedId : null;
  const navigate = useNavigate();
  const gp = useCommunityPath();

  const target = useMemo(() => (id === null ? null : sharedTarget(tool, id)), [tool, id]);
  const set = useToolLayouts(target).data;
  const shared = SHARED_LAYOUTS[tool];
  const details = useMemo(() => (id === null || !shared ? [] : [shared.detail(id)]), [id, shared]);
  const presets = useMemo(() => (id === null ? undefined : shared?.presets?.(id)), [id, shared]);

  if (!set || !target || id === null) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="initiative" />;
  return (
    <LayoutEditor
      // Another initiative's editor starts afresh: a draft, and the question
      // before leaving it, belong to the initiative they were made for.
      key={`${tool}:${id}`}
      target={target}
      initiativeId={id}
      presets={presets}
      details={details}
      set={set}
      onClose={() => void navigate({ to: gp(`${initiativeRoute(id)}/settings/layouts`) })}
    />
  );
};
