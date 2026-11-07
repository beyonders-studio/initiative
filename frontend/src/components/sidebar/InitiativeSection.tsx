import { Link } from "@tanstack/react-router";
import { Blocks, CircleChevronRight, MoreVertical, Settings, ShieldAlert } from "lucide-react";
import { memo, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityPluginRead,
  InitiativeRead,
  ProjectRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/sidebar/sidebar";
import { ToolCreateButton } from "@/components/tools/ToolCreateButton";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { communityPath } from "@/lib/communityUrl";
import { initiativePluginPath } from "@/lib/pluginSurfaces";
import { getItem, setItem } from "@/lib/storage";
import {
  initiativeRoute,
  SIDEBAR_TOOLS,
  TOOL_ICONS,
  toolDetailRoute,
  toolListRoute,
  toolNavLabelKey,
} from "@/lib/tools";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

export interface InitiativeSectionProps {
  initiative: InitiativeRead;
  projects: ProjectRead[];
  activeProjectId: number | null;
  /** Per-tool sidebar counts. Every in-app list tool shows one — the rows all
   *  present the same way; a hand-off (embedded) tool has no list to count. */
  /** One count per tool. Required keys, not `Partial`: a tool left out of
   *  this map renders a permanent 0 with nothing to catch it. */
  counts: Record<Tool, number>;
  /** The community's installed plug-ins. Those declaring a surface for this reader
   *  inside an initiative get a row here, drawn from the same one install. */
  plugins: CommunityPluginRead[];
  activeCommunityId: number | null;
  /** Changing this value re-syncs the open/closed state from storage. */
  collapseKey?: number;
}

export const InitiativeSection = memo(
  ({
    initiative,
    projects,
    activeProjectId,
    counts,
    plugins,
    activeCommunityId,
    collapseKey,
  }: InitiativeSectionProps) => {
    const { t } = useTranslation("nav");
    // The same signal the community rail carries, one level in and then one
    // more: a dot on the initiative, and on the tool inside it.
    const unread = useUnreadTree();
    // Helper to create community-scoped paths
    const gp = (path: string) =>
      activeCommunityId ? communityPath(activeCommunityId, path) : path;
    /** Whether a tool's row renders at all. */
    const showTool = (tool: Tool): boolean => initiative.can.view.includes(tool);

    /** Whether to surface a create affordance for a tool. */
    const canCreateTool = (tool: Tool): boolean => initiative.can.create.includes(tool);

    // Plug-ins offering this reader a surface inside *this* initiative, as the
    // server computed it for them.
    const pluginRows = plugins
      .map((plugin) => ({ plugin, path: initiativePluginPath(plugin, initiative.id) }))
      .filter((row): row is { plugin: CommunityPluginRead; path: string } => row.path !== null);

    // Load initial state from storage, default to true if not found
    const [isOpen, setIsOpen] = useState(() => {
      try {
        const stored = getItem("initiative-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<number, boolean>;
          return states[initiative.id] ?? true;
        }
      } catch {
        // Ignore parsing errors
      }
      return true;
    });

    // Save state to storage whenever it changes
    useEffect(() => {
      try {
        const stored = getItem("initiative-collapsed-states");
        const states = stored ? (JSON.parse(stored) as Record<number, boolean>) : {};
        states[initiative.id] = isOpen;
        setItem("initiative-collapsed-states", JSON.stringify(states));
      } catch {
        // Ignore storage errors
      }
    }, [isOpen, initiative.id]);

    // Re-sync from storage when collapseKey changes (collapse/expand all)
    useEffect(() => {
      if (collapseKey === undefined) return;
      try {
        const stored = getItem("initiative-collapsed-states");
        if (stored) {
          const states = JSON.parse(stored) as Record<number, boolean>;
          setIsOpen(states[initiative.id] ?? true);
        }
      } catch {
        // Ignore parsing errors
      }
    }, [collapseKey, initiative.id]);

    return (
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <div className="group/initiative flex min-w-0 items-center gap-1">
          <div className="flex min-w-0 flex-1 items-center">
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                aria-label={isOpen ? t("collapseInitiative") : t("expandInitiative")}
              >
                <CircleChevronRight
                  className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                  style={{ color: initiative.color || undefined }}
                />
              </Button>
            </CollapsibleTrigger>
            <Button
              variant="ghost"
              className="min-w-0 flex-1 justify-start px-0 py-1.5 font-medium text-sm hover:bg-accent"
              asChild
            >
              <Link
                to={gp(initiativeRoute(initiative.id))}
                className="flex min-w-0 items-center gap-2"
              >
                <span className="min-w-0 flex-1 truncate text-left">{initiative.name}</span>
                {unread.hasInitiative(activeCommunityId, initiative.id) ? <UnreadDot /> : null}
              </Link>
            </Button>
          </div>
          {initiative.can.manage && (
            <>
              {/* Desktop: Show hover-reveal settings button */}
              <Tooltip delayDuration={300}>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover/initiative:w-6 group-hover/initiative:opacity-100 motion-reduce:transition-none md:flex"
                    asChild
                  >
                    <Link to={gp(`${initiativeRoute(initiative.id)}/settings`)}>
                      <Settings className="h-3 w-3" />
                    </Link>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <p>{t("initiativeSettings")}</p>
                </TooltipContent>
              </Tooltip>

              {/* Mobile: Show three-dot menu. modal={false}: a modal dropdown
                  nested in the non-modal mobile sidebar drawer dismisses the
                  drawer on open (matches the user-footer dropdown). */}
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0 md:hidden"
                    aria-label={t("initiativeActions")}
                  >
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem asChild>
                    <Link to={gp(`${initiativeRoute(initiative.id)}/settings`)}>
                      <Settings className="h-4 w-4" />
                      {t("initiativeSettings")}
                    </Link>
                  </DropdownMenuItem>
                  {SIDEBAR_TOOLS.filter(canCreateTool).map((tool) => (
                    <ToolCreateButton
                      key={tool}
                      tool={tool}
                      initiativeId={initiative.id}
                      variant="menu-item"
                    />
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}
        </div>
        {isOpen && (
          <CollapsibleContent
            className="ml-3 space-y-0.5 border-l"
            style={{ borderColor: initiative.color || undefined }}
            forceMount
          >
            <SidebarMenu>
              {/* Moderation sits above everything, for the people who moderate.
                  It is not a tool — nothing shares it, nothing turns it off —
                  and it is drawn only for whoever already reaches every item in
                  the initiative, which is what the tables themselves admit. */}
              {initiative.can.moderate && (
                <SidebarMenuItem>
                  <SidebarMenuButton asChild size="sm" className="min-w-0">
                    <Link
                      to={gp(`${initiativeRoute(initiative.id)}/moderation`)}
                      className="flex min-w-0 items-center gap-2"
                    >
                      <ShieldAlert className="h-4 w-4 shrink-0" />
                      <span className="min-w-0 flex-1 truncate">{t("moderation")}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              )}

              {/* Plug-ins first, above the tools, the same way the community's plug-ins sit
                  above its initiatives — and because the tool rows end with
                  projects, whose list has to expand directly beneath them. */}
              {pluginRows.map(({ plugin, path }) => (
                <SidebarMenuItem key={`plugin-${plugin.id}`}>
                  <SidebarMenuButton asChild size="sm" className="min-w-0">
                    <Link to={gp(path)} className="flex min-w-0 items-center gap-2">
                      {plugin.avatar_url ? (
                        <img
                          src={resolveArtworkUrl(plugin.avatar_url) ?? undefined}
                          alt=""
                          aria-hidden
                          className="h-4 w-4 shrink-0 rounded-sm object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <Blocks className="h-4 w-4 shrink-0" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{plugin.name}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}

              {/* One row per tool, in SIDEBAR_TOOLS order (projects last so
                  the project list expands directly beneath their row). */}
              {SIDEBAR_TOOLS.filter(showTool).map((tool) => {
                const Icon = TOOL_ICONS[tool];
                const rowTo = toolListRoute(tool, initiative.id);
                return (
                  <SidebarMenuItem key={tool}>
                    <div className="group/tool flex w-full min-w-0 items-center gap-1">
                      <SidebarMenuButton asChild size="sm" className="min-w-0 flex-1">
                        <Link to={gp(rowTo)} className="flex min-w-0 items-center gap-2">
                          <Icon className="h-4 w-4" />
                          <span className="min-w-0 flex-1 truncate">
                            {t(toolNavLabelKey(tool))}
                          </span>
                          {unread.hasTool(activeCommunityId, initiative.id, tool) ? (
                            <UnreadDot />
                          ) : null}
                          <span className="text-muted-foreground text-xs">{counts[tool] ?? 0}</span>
                        </Link>
                      </SidebarMenuButton>
                      {canCreateTool(tool) && (
                        <ToolCreateButton tool={tool} initiativeId={initiative.id} variant="icon" />
                      )}
                    </div>
                  </SidebarMenuItem>
                );
              })}

              {/* Projects List */}
              {showTool(Tool.project) &&
                projects.map((project) => (
                  <SidebarMenuItem key={project.id}>
                    <div className="group/project flex w-full min-w-0 items-center gap-1">
                      <SidebarMenuButton
                        asChild
                        size="sm"
                        className="min-w-0 flex-1"
                        isActive={project.id === activeProjectId}
                      >
                        <Link
                          to={gp(toolDetailRoute(Tool.project, initiative.id, project.id))}
                          className="flex min-w-0 items-center gap-2"
                        >
                          {project.icon ? (
                            <span className="shrink-0 text-base">{project.icon}</span>
                          ) : null}
                          <span className="min-w-0 flex-1 truncate">{project.name}</span>
                        </Link>
                      </SidebarMenuButton>
                      {project.can.edit && (
                        <>
                          {/* Desktop: Show hover-reveal settings button */}
                          <Tooltip delayDuration={300}>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all group-hover/project:w-6 group-hover/project:opacity-100 motion-reduce:transition-none md:flex"
                                asChild
                              >
                                <Link
                                  to={gp(
                                    `${toolDetailRoute(Tool.project, initiative.id, project.id)}/settings`
                                  )}
                                >
                                  <Settings className="h-3 w-3" />
                                </Link>
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent side="top">
                              <p>{t("projectSettings")}</p>
                            </TooltipContent>
                          </Tooltip>

                          {/* Mobile: Show three-dot menu. modal={false}: a modal
                              dropdown nested in the non-modal mobile sidebar
                              drawer dismisses the drawer on open (matches the
                              user-footer dropdown). */}
                          <DropdownMenu modal={false}>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 shrink-0 md:hidden"
                                aria-label={t("projectActions")}
                              >
                                <MoreVertical className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-48">
                              <DropdownMenuItem asChild>
                                <Link
                                  to={gp(
                                    `${toolDetailRoute(Tool.project, initiative.id, project.id)}/settings`
                                  )}
                                >
                                  <Settings className="h-4 w-4" />
                                  {t("projectSettings")}
                                </Link>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </>
                      )}
                    </div>
                  </SidebarMenuItem>
                ))}
            </SidebarMenu>
          </CollapsibleContent>
        )}
      </Collapsible>
    );
  }
);
InitiativeSection.displayName = "InitiativeSection";
