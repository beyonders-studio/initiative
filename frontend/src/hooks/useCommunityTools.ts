/**
 * The community's tools, as the screens that switch them and say who may use
 * them list them: the built-in tools in sidebar order, then the tool each
 * tool plug-in declares, in the order they were installed.
 *
 * A tool plug-in's tool is a tool like any built-in inside an initiative its
 * install is placed in: the initiative's own switch and each role's keys
 * govern it there. In an initiative it is not placed in, it is absent.
 */

import type { LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { installedTool, toolText } from "@/lib/toolPlugins";
import { SIDEBAR_TOOLS, TOOL_ICONS, toolCamelPlural } from "@/lib/tools";

/** One of the community's tools. */
export interface CommunityTool {
  /** Its kind, which names its switch and its role keys. */
  kind: string;
  /** The built-in tool it is; null for a tool plug-in's. */
  builtIn: Tool | null;
  /** Its name in the reader's language. */
  name: string;
  icon: LucideIcon;
  /** The name of the plug-in that declares it; null for a built-in tool. */
  plugin: string | null;
  /** The initiatives its install is placed in; null for a built-in tool,
   *  which every initiative has. */
  placedIn: readonly number[] | null;
}

/** A built-in tool as one of the community's tools. */
export const builtInTool = (tool: Tool, t: (key: never) => string): CommunityTool => ({
  kind: tool,
  builtIn: tool,
  name: t(`initiatives:${toolCamelPlural(tool)}Feature` as never),
  icon: TOOL_ICONS[tool],
  plugin: null,
  placedIn: null,
});

/** The community's tools. With `initiativeId`, only those that initiative
 *  has: every built-in tool, and the tool plug-ins on in the community and
 *  placed in it. Without, every installed one, switched off or not, since
 *  what the community set for a tool outlives its install's switch. */
export const useCommunityTools = (initiativeId?: number): CommunityTool[] => {
  const { t, i18n } = useTranslation("initiatives");
  const plugins = useCommunityPlugins().data?.items;
  return useMemo(() => {
    const installed = (plugins ?? []).flatMap((plugin): CommunityTool[] => {
      const tool = installedTool(plugin);
      const here =
        initiativeId === undefined ||
        (plugin.enabled &&
          plugin.available !== false &&
          plugin.placed_initiative_ids.includes(initiativeId));
      if (!tool || !here) return [];
      return [
        {
          kind: tool.kind,
          builtIn: null,
          name: toolText(tool.name, i18n.language),
          icon: tool.icon,
          plugin: plugin.name,
          placedIn: plugin.placed_initiative_ids,
        },
      ];
    });
    const translate = t as unknown as (key: never) => string;
    return [...SIDEBAR_TOOLS.map((tool) => builtInTool(tool, translate)), ...installed];
  }, [plugins, initiativeId, t, i18n.language]);
};
