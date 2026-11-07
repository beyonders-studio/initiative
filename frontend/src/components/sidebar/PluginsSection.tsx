/**
 * The community's installed plug-ins, above its initiatives.
 *
 * Plug-ins are community-wide surfaces, so they sit above the initiatives rather than
 * inside any of them. What shows depends on who is looking:
 *
 * - **Plug-ins installed** — one entry each, for everyone. Whether a member may do
 *   anything *inside* one is that instance's own sharing, enforced where the
 *   content lives.
 * - **No plug-ins** — the section still shows, for everyone. A member cannot add
 *   one, but they can look at what exists and ask for it, so the shelf is worth
 *   pointing at; what differs is the invitation at the bottom.
 *
 * A surface names the audience it is for, and an entry is only offered to a
 * reader who is in it — a plug-in whose only community-wide surface is for admins does
 * not take a row for a member. The mint settles the same question again under
 * the caller's own session; this is about not pointing at a closed door.
 *
 * Disabled plug-ins are hidden here and stay visible in community settings, which is
 * where an admin turns them back on. So are plug-ins whose service is not set up on
 * this server — an entry that opens nothing is worse than no entry, and community
 * settings is where that state is explained.
 *
 * **Every entry does something.** A plug-in with a surface opens it; a plug-in with
 * only a credential to supply opens that form where it stands, because "set up
 * my GitHub account" is the plug-in, not a detour through settings. A plug-in that is
 * neither — one contributing widgets or data to somewhere else — has nothing to
 * open, so it sits under a "show more" rather than spending a row on a click
 * that would go nowhere.
 */

import { Link } from "@tanstack/react-router";
import {
  Blocks,
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  Plus,
  Settings2,
  Store,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type CommunityPluginRead, ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { PluginSettingsDialog } from "@/components/plugins/PluginSettingsDialog";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/sidebar/sidebar";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useCommunityPath } from "@/lib/communityUrl";
import { communityPluginPath, pluginHasConnections } from "@/lib/pluginSurfaces";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui/tooltip";

export interface PluginsSectionProps {
  isCommunityAdmin: boolean;
  /** Persisted open/closed state, keyed like the other sidebar sections. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PluginsSection({ isCommunityAdmin, open, onOpenChange }: PluginsSectionProps) {
  const { t } = useTranslation(["plugins", "nav"]);
  const gp = useCommunityPath();
  const pluginsQuery = useCommunityPlugins();
  const [showInert, setShowInert] = useState(false);

  // `available` is false when a plug-in's service is not set up on this server, or
  // the operator switched it off: there is nothing behind the entry, so it does
  // not appear. Community settings still lists it, which is where that is said.
  const plugins = (pluginsQuery.data?.items ?? []).filter(
    (plugin) => plugin.enabled && plugin.available !== false
  );

  // A plug-in with somewhere to go leads; one with nothing to open waits under
  // "show more" so a community that installs many widget providers still has a
  // readable sidebar. A surface the server says this reader cannot open is not
  // somewhere they can go, so for them it does not count as one.
  const actionable = plugins.filter(
    (plugin) => communityPluginPath(plugin) !== null || pluginHasConnections(plugin.definition)
  );
  const inert = plugins.filter((plugin) => !actionable.includes(plugin));

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <SidebarGroup>
        <SidebarGroupLabel className="flex items-center gap-2 py-2">
          <Blocks className="h-4 w-4" />
          <CollapsibleTrigger className="flex flex-1 items-center text-left">
            <span className="flex-1">{t("plugins:title")}</span>
          </CollapsibleTrigger>
          {plugins.length > 0 && (
            <Tooltip delayDuration={300}>
              <TooltipTrigger asChild>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 shrink-0"
                    aria-label={open ? t("nav:collapseAll") : t("nav:expandAll")}
                  >
                    {open ? (
                      <ChevronsDownUp className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronsUpDown className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </CollapsibleTrigger>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p>{open ? t("nav:collapseAll") : t("nav:expandAll")}</p>
              </TooltipContent>
            </Tooltip>
          )}
        </SidebarGroupLabel>

        <CollapsibleContent>
          <SidebarGroupContent>
            {plugins.length ? (
              <SidebarMenu>
                {actionable.map((plugin) => (
                  <PluginEntry
                    key={plugin.id}
                    plugin={plugin}
                    isCommunityAdmin={isCommunityAdmin}
                  />
                ))}
                {showInert &&
                  inert.map((plugin) => (
                    <PluginEntry
                      key={plugin.id}
                      plugin={plugin}
                      isCommunityAdmin={isCommunityAdmin}
                    />
                  ))}
                {inert.length > 0 && (
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      size="sm"
                      onClick={() => setShowInert((shown) => !shown)}
                      className="text-muted-foreground"
                    >
                      <ChevronDown
                        className={cn("h-4 w-4 transition-transform", !showInert && "-rotate-90")}
                        aria-hidden
                      />
                      <span className="truncate">
                        {showInert
                          ? t("plugins:showFewer")
                          : t("plugins:showMore", { count: inert.length })}
                      </span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )}
              </SidebarMenu>
            ) : (
              <p className="px-4 py-2 text-muted-foreground text-sm">{t("plugins:none")}</p>
            )}

            {/* Last, below "show more" as well, so it is always in the same
                place — the same shape the initiatives list uses. An admin adds
                one; everyone else browses the same shelf, where a listing says
                who to ask. */}
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild size="sm">
                  <Link to={gp("/marketplace")} search={{ kind: ListingKind.plugin }}>
                    {isCommunityAdmin ? (
                      <Plus className="h-4 w-4" />
                    ) : (
                      <Store className="h-4 w-4" />
                    )}
                    <span>{isCommunityAdmin ? t("plugins:add") : t("plugins:browse")}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

function PluginEntry({
  plugin,
  isCommunityAdmin,
}: {
  plugin: CommunityPluginRead;
  isCommunityAdmin: boolean;
}) {
  const { t } = useTranslation(["plugins"]);
  const gp = useCommunityPath();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const path = communityPluginPath(plugin);
  // The listing's own artwork, small. Every listing has one — a listing that
  // ships none is published with the plug-in's own mark — so there is nothing to
  // fall back to.
  const icon = plugin.avatar_url ? (
    <img
      src={resolveArtworkUrl(plugin.avatar_url) ?? undefined}
      alt=""
      aria-hidden
      className="h-4 w-4 shrink-0 rounded-sm object-cover"
      loading="lazy"
    />
  ) : (
    <Blocks className="h-4 w-4" />
  );

  // Every plug-in has settings, so every entry carries the gear. It waits for a
  // hover (or a keyboard focus) so a row reads as the plug-in's name rather than a
  // pair of controls.
  const settings = (
    <>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <SidebarMenuAction
            showOnHover
            onClick={() => setSettingsOpen(true)}
            aria-label={t("plugins:settings.open", { name: plugin.name })}
          >
            <Settings2 className="h-4 w-4" aria-hidden />
          </SidebarMenuAction>
        </TooltipTrigger>
        <TooltipContent side="right">
          <p>{t("plugins:settings.open", { name: plugin.name })}</p>
        </TooltipContent>
      </Tooltip>
      <PluginSettingsDialog
        pluginId={plugin.id}
        isCommunityAdmin={isCommunityAdmin}
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
      />
    </>
  );

  if (path) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton asChild size="sm">
          <Link to={gp(path)}>
            {icon}
            <span className="truncate">{plugin.name}</span>
          </Link>
        </SidebarMenuButton>
        {settings}
      </SidebarMenuItem>
    );
  }

  // No surface, but something to connect: clicking the name opens the settings
  // where the member stands rather than sending them to find the same form.
  if (pluginHasConnections(plugin.definition)) {
    return (
      <SidebarMenuItem>
        <SidebarMenuButton size="sm" onClick={() => setSettingsOpen(true)}>
          {icon}
          <span className="truncate">{plugin.name}</span>
        </SidebarMenuButton>
        {settings}
      </SidebarMenuItem>
    );
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton size="sm" className="cursor-default hover:bg-transparent">
        {icon}
        <span className="truncate">{plugin.name}</span>
      </SidebarMenuButton>
      {settings}
    </SidebarMenuItem>
  );
}
