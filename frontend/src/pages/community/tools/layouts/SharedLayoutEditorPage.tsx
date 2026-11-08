/**
 * `/<tool>/layouts` — the layouts of a tool the whole initiative shares (its
 * calendar's event detail and list, its notices' detail), laid out in place.
 *
 * Who may is the server's answer on the set (the initiative's managers, a
 * community admin). The editor itself says when the screen is too narrow to
 * edit on, and keeps its draft while it is.
 */

import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SHARED_LAYOUTS } from "@/components/layouts/details";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { LAYOUT_NAMESPACES } from "@/hooks/useLayoutEnv";
import { NO_DEFINITIONS } from "@/hooks/useProperties";
import { usePropertyEnv } from "@/hooks/usePropertyEnv";
import { useRouteId } from "@/hooks/useRouteId";
import { sharedTarget, useSaveLayouts, useToolLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { useLayoutPlugins } from "@/lib/layouts/plugins";
import { initiativeRoute } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";
import { LayoutEditor } from "@/ui/layouts/LayoutEditor";

export const SharedLayoutEditorPage = ({ tool }: { tool: Tool }) => {
  const id = useRouteId("initiativeId");
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const { t } = useTranslation(LAYOUT_NAMESPACES);

  const target = useMemo(() => (id === null ? null : sharedTarget(tool, id)), [tool, id]);
  const set = useToolLayouts(target).data;
  const save = useSaveLayouts(target ?? sharedTarget(tool, 0));
  const shared = SHARED_LAYOUTS[tool];
  const details = useMemo(() => (id === null || !shared ? [] : [shared.detail(id)]), [id, shared]);
  const plugins = useLayoutPlugins(id, details[0]?.spec.kind);
  const propertyEnv = usePropertyEnv({ initiativeId: id, enabled: true });
  const { definitions, appendOption, searchMembers } = propertyEnv;
  const presets = useMemo(
    () => shared?.presets?.(definitions.data ?? NO_DEFINITIONS, { appendOption, searchMembers }),
    [shared, definitions.data, appendOption, searchMembers]
  );

  if (!set || !target || id === null) return null;
  if (!set.can_configure) return <SettingsPermissionRequired scope="initiative" />;
  return (
    <LayoutEditor
      // Another initiative's editor starts afresh: a draft, and the question
      // before leaving it, belong to the initiative they were made for.
      key={`${tool}:${id}`}
      t={t as TranslateFn}
      initiativeId={id}
      presets={presets}
      details={details}
      plugins={plugins}
      propertyEnv={propertyEnv}
      layouts={set}
      save={save.mutateAsync}
      metadataHref={gp(`${initiativeRoute(id)}/settings/properties`)}
      onClose={() => void navigate({ to: gp(`${initiativeRoute(id)}/settings/layouts`) })}
    />
  );
};
