import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolCreateLabelKey, toolCreateTarget } from "@/lib/tools";
import { Button } from "@/ui/button";
import { DropdownMenuItem } from "@/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui/tooltip";

/**
 * The single source of "how do I create this tool" — derived entirely from the
 * registry, so adding a tool gives it a create affordance automatically: every
 * tool navigates to its list route's create dialog.
 */
export function useToolCreate(tool: Tool, initiativeId: number) {
  const gp = useCommunityPath();
  const { t } = useTranslation("nav");

  const target = toolCreateTarget(tool, initiativeId);
  const to = gp(target.to);
  const label = t(toolCreateLabelKey(tool));

  return { to, search: target.search, label };
}

type ToolCreateButtonProps = {
  tool: Tool;
  initiativeId: number;
  /**
   * `icon` — hover-reveal "+" for a sidebar tool row (expects a `group/tool`
   * ancestor). `menu-item` — a dropdown entry. `button` — a full "New X" button.
   */
  variant: "icon" | "menu-item" | "button";
};

/**
 * The one create affordance reused across every surface. All per-tool behavior
 * (destination, label) comes from `useToolCreate`; this only chooses the
 * presentation.
 */
export function ToolCreateButton({ tool, initiativeId, variant }: ToolCreateButtonProps) {
  const { to, search, label } = useToolCreate(tool, initiativeId);

  if (variant === "menu-item") {
    return (
      <DropdownMenuItem asChild>
        <Link to={to} search={search}>
          <Plus className="h-4 w-4" />
          {label}
        </Link>
      </DropdownMenuItem>
    );
  }

  if (variant === "button") {
    return (
      <Button asChild size="sm">
        <Link to={to} search={search}>
          <Plus className="h-4 w-4" />
          {label}
        </Link>
      </Button>
    );
  }

  return (
    <Tooltip delayDuration={300}>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover/tool:w-6 group-hover/tool:opacity-100 motion-reduce:transition-none md:flex"
          asChild
        >
          <Link to={to} search={search} aria-label={label}>
            <Plus className="h-3 w-3" />
          </Link>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p>{label}</p>
      </TooltipContent>
    </Tooltip>
  );
}
