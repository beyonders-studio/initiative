/**
 * `/settings/layouts` — how a tool lays out what it holds: each of its
 * layouts, when it was last changed, and, for a project, which views it shows
 * and the one it opens on, with the way into the layout editor.
 *
 * Changing them is a step above write access (the tool's owner, the
 * initiative's managers, or a community admin). The server decides, and says
 * so on the set. The tab bar offers this section only then, and the section
 * refuses anyone else on its own too, since the address is typeable.
 */

import { useTranslation } from "react-i18next";

import { LayoutsOverview } from "@/components/layouts/LayoutList";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { instanceTarget, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";

export const ToolSettingsLayoutsPage = () => {
  const { tool, entity } = useToolSettings();
  const { t } = useTranslation("layouts");
  const gp = useCommunityPath();
  const set = useInstanceLayouts(tool, entity.id).data;

  if (!set) return null;
  if (!set.can_configure) return <ToolSettingsPermissionRequired />;

  const editor = gp(`${toolDetailRoute(tool, entity.initiative_id, entity.id)}/layouts`);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("tab")}</CardTitle>
        <CardDescription>{t("settingsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <LayoutsOverview
          layouts={set.layouts}
          target={instanceTarget(tool, entity.id)}
          editor={editor}
        />
      </CardContent>
    </Card>
  );
};
