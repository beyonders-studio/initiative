/**
 * `/settings/layouts` — how each tool in this initiative draws what it holds,
 * in the sidebar's order: the calendar's and the notices' details, and each
 * project's, queue's, library's and counter group's layouts. Each layout says when it was last changed, and a project which list
 * it opens on; each has a way into its layout editor.
 */

import { Link } from "@tanstack/react-router";
import { Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type InitiativeToolLayoutsRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { SHARED_LAYOUTS } from "@/components/layouts/details";
import { LayoutList } from "@/components/layouts/LayoutList";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import {
  INSTANCE_LAYOUT_TOOLS,
  instanceTarget,
  sharedTarget,
  useInitiativeLayouts,
  useToolLayouts,
} from "@/hooks/useToolLayouts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { useCommunityPath } from "@/lib/communityUrl";
import {
  isToolEnabled,
  SIDEBAR_TOOLS,
  toolDetailRoute,
  toolListRoute,
  toolNavLabelKey,
} from "@/lib/tools";

export const InitiativeSettingsLayoutsPage = () => {
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();
  if (!canManageMembers) return <InitiativeSettingsPermissionRequired />;
  return (
    <InitiativeLayouts
      initiativeId={initiativeId}
      enabled={(tool) => initiative !== null && isToolEnabled(tool, initiative)}
    />
  );
};

/** The tools with layouts, in the order the sidebar lists them. */
const TOOLS_WITH_LAYOUTS = SIDEBAR_TOOLS.filter(
  (tool) => tool in SHARED_LAYOUTS || INSTANCE_LAYOUT_TOOLS.has(tool)
);

const InitiativeLayouts = ({
  initiativeId,
  enabled,
}: {
  initiativeId: number;
  /** Whether the initiative has a tool it shares on. */
  enabled: (tool: Tool) => boolean;
}) => {
  const { t } = useTranslation("initiatives");
  const { data, isError } = useInitiativeLayouts(initiativeId);
  // Each tool's instances; an initiative with no project yet says so.
  const instances = (tool: Tool) => {
    const entries = data?.filter((entry) => entry.tool === tool);
    if (tool === Tool.project && entries?.length === 0) {
      return <p className="text-muted-foreground text-sm">{t("settings.layouts.noProjects")}</p>;
    }
    return entries?.map((entry) => (
      <InstanceLayouts key={entry.tool_id} initiativeId={initiativeId} entry={entry} />
    ));
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.layouts.heading")}</CardTitle>
        <CardDescription>{t("settings.layouts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isError ? (
          <p className="text-destructive text-sm">{t("settings.layouts.loadError")}</p>
        ) : null}
        {TOOLS_WITH_LAYOUTS.map((tool) =>
          tool in SHARED_LAYOUTS ? (
            enabled(tool) ? (
              <SharedLayouts key={tool} tool={tool} initiativeId={initiativeId} />
            ) : null
          ) : (
            <div key={tool} className="space-y-3">
              {instances(tool)}
            </div>
          )
        )}
      </CardContent>
    </Card>
  );
};

/** One instance's layouts (a project's, a queue's), opening its editor where
 *  the reader may change them and has the room the editor needs. */
const InstanceLayouts = ({
  initiativeId,
  entry,
}: {
  initiativeId: number;
  entry: InitiativeToolLayoutsRead;
}) => {
  const { t } = useTranslation(["projects", "layouts"]);
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const instance = gp(toolDetailRoute(entry.tool, initiativeId, entry.tool_id));
  const editor = `${instance}/layouts`;
  return (
    <section aria-label={entry.name} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={instance} className="font-medium hover:underline">
          {entry.name}
        </Link>
        {entry.can_configure && wide ? (
          <Button asChild variant="outline" size="sm">
            <Link to={editor}>
              <Pencil className="h-4 w-4" />
              {t("layouts:open")}
            </Link>
          </Button>
        ) : null}
      </div>
      <LayoutList
        layouts={entry.layouts}
        target={entry.can_configure ? instanceTarget(entry.tool, entry.tool_id) : undefined}
      />
    </section>
  );
};

/** The layouts a tool the whole initiative shares keeps (the calendar's event
 *  detail, the notices' detail), opening its editor where the reader may
 *  change them and has the room. */
const SharedLayouts = ({ tool, initiativeId }: { tool: Tool; initiativeId: number }) => {
  const { t } = useTranslation(["nav", "layouts"]);
  const gp = useCommunityPath();
  const wide = atLeast(useWidthClass(), "md");
  const set = useToolLayouts(sharedTarget(tool, initiativeId)).data;
  if (!set) return null;
  const list = gp(toolListRoute(tool, initiativeId));
  const editor = `${list}/layouts`;
  // A shared tool's own list draws nothing a layout can change yet.
  const details = set.layouts.filter((layout) => !("is_default" in layout));
  const name = t(toolNavLabelKey(tool));
  return (
    <section aria-label={name} className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link to={list} className="font-medium hover:underline">
          {name}
        </Link>
        {set.can_configure && wide ? (
          <Button asChild variant="outline" size="sm">
            <Link to={editor}>
              <Pencil className="h-4 w-4" />
              {t("layouts:open")}
            </Link>
          </Button>
        ) : null}
      </div>
      <LayoutList layouts={details} />
    </section>
  );
};
