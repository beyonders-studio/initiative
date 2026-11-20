/**
 * The kinds a reference may name in the active community, and how each is
 * drawn: the built-in kinds, then every table of each tool plug-in it has
 * installed (`counter_group.tsjvtcm0s7gv2x`, `counter.tsjvtcm0s7gv2x`).
 */

import type { LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { MENTIONABLE_TYPES } from "@/lib/mentions";
import { entityIcon } from "@/lib/searchResults";
import { type InstalledTool, selectInstalledTools, toolOfKind, toolText } from "@/lib/toolPlugins";

const NO_TOOLS: InstalledTool[] = [];

export interface ReferenceKinds {
  /** What `#` and `![[ ]]` offer: every kind a reference may name. */
  mentionable: string[];
  /** What a kind is called where a reference names it: a tool plug-in's
   *  table by its own name, in the reader's language. */
  label: (kind: string) => string;
  /** The mark a kind is drawn with: a tool plug-in's tool's icon. */
  icon: (kind: string) => LucideIcon;
}

export const useReferenceKinds = (): ReferenceKinds => {
  const { t, i18n } = useTranslation("search");
  const tools = useCommunityPlugins({ select: selectInstalledTools }).data ?? NO_TOOLS;
  return useMemo(
    () => ({
      mentionable: [...MENTIONABLE_TYPES, ...tools.flatMap((tool) => [...tool.tables.keys()])],
      label: (kind) => {
        const found = toolOfKind(tools, kind);
        return found
          ? toolText(found.table.name, i18n.language)
          : t(`types.${kind}` as never, { defaultValue: kind });
      },
      icon: (kind) => toolOfKind(tools, kind)?.tool.icon ?? entityIcon(kind),
    }),
    [tools, t, i18n.language]
  );
};
