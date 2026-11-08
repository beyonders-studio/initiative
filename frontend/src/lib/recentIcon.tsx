import type { ReactNode } from "react";

import { type PersonalItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_ICONS } from "@/lib/tools";
import { fileIcon } from "@/ui/lib/fileIcon";
import { cn } from "@/ui/lib/utils";

/**
 * Render the entity-specific icon for a tool in a list of them: a recent tab,
 * a bookmarked tool.
 *
 * - Projects show the emoji icon set on the project itself.
 * - Files resolve to the same icon + color used in file lists
 *   (via ``fileIcon``).
 * - Every other tool renders its registry icon.
 */
export function renderRecentIcon(item: PersonalItemRead): ReactNode {
  switch (item.entity_type) {
    case Tool.project: {
      if (!item.icon) return null;
      return <span className="text-base leading-none">{item.icon}</span>;
    }
    case Tool.file: {
      const { Icon, colorClass } = fileIcon(item);
      return <Icon className={cn("h-4 w-4", colorClass)} />;
    }
    default: {
      const Icon = TOOL_ICONS[item.entity_type as Tool];
      return Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null;
    }
  }
}
