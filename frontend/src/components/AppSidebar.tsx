import { Link, useLocation } from "@tanstack/react-router";
import {
  Binoculars,
  Bookmark,
  Check,
  ChevronsDownUp,
  ChevronsUpDown,
  Pencil,
  Plus,
  Settings,
  Tag,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { AdminSurface, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CommunitySidebar } from "@/components/communities/CommunitySidebar";
import { DIRECTORY_SECTION_ID } from "@/components/communityHome/InitiativeDirectory";
import { InitiativeMark } from "@/components/icons/InitiativeMark";
import { CommunityDirectorySidebar } from "@/components/sidebar/CommunityDirectorySidebar";
import { HomeSidebarContent } from "@/components/sidebar/HomeSidebarContent";
import { InitiativeSection } from "@/components/sidebar/InitiativeSection";
import { PluginsSection } from "@/components/sidebar/PluginsSection";
import { SidebarSearchButton } from "@/components/sidebar/SidebarSearchButton";
import { SidebarUserFooter } from "@/components/sidebar/SidebarUserFooter";
import { TagBrowser } from "@/components/sidebar/TagBrowser";
import { WikiSidebarContent } from "@/components/sidebar/WikiSidebarContent";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useAutoCloseSidebar } from "@/hooks/useAutoCloseSidebar";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useHeldSurfaces } from "@/hooks/useCustomRoles";
import { liveInitiatives } from "@/hooks/useInitiativeAccess";
import { useInitiativeDirectory, useInitiatives } from "@/hooks/useInitiatives";
import { compareVersions, useLatestVersion } from "@/hooks/useLatestVersion";
import { useCommunityBookmarks } from "@/hooks/usePersonalItems";
import { useProjects } from "@/hooks/useProjects";
import { useTags } from "@/hooks/useTags";
import { useToolCountsByInitiative } from "@/hooks/useToolCounts";
import { atLeast, useWidthClass } from "@/hooks/useWidthClass";
import { communityPath } from "@/lib/communityUrl";
import { canAccessOperatorDashboard, canManagePlatformConfig } from "@/lib/permissions";
import { renderRecentIcon } from "@/lib/recentIcon";
import { getActiveRecentKey, recentRoute } from "@/lib/recentRoute";
import { getItem, setItem } from "@/lib/storage";
import { TOOLS, toolViewParams } from "@/lib/tools";

export const AppSidebar = () => {
  const { user, logout, refreshUser } = useAuth();
  const { communityDirectoryEnabled, isLoading: configLoading } = useAppConfig();
  const { activeCommunity, activeCommunityId } = useCommunities();
  const isMobile = !atLeast(useWidthClass(), "md");
  const location = useLocation();
  const { t } = useTranslation(["nav", "tags", "initiatives"]);

  // Auto-close sidebar on mobile after navigation
  useAutoCloseSidebar();

  // Community admin check is based on community membership role only (independent from platform role).
  // Used for community-settings affordances; what the reader may do inside each
  // initiative is that initiative's own `can`.
  // The gear opens the community's own configuration, which a settings
  // grant reaches as well as its admin does.
  const isCommunityAdmin = Boolean(activeCommunity?.can.administer);
  // The gear shows for anybody who runs any part of the community, a custom
  // role included.
  const heldSurfaces = useHeldSurfaces();
  const showsCommunitySettings = isCommunityAdmin || heldSurfaces.holdsAny;
  // Making an initiative is part of running the community's initiatives.
  const createsInitiatives = heldSurfaces.holds(AdminSurface.initiatives);
  // Two separate platform areas: config (Platform settings) vs operational
  // (Operator dashboard). Each surfaced independently per capability.
  const showPlatformSettings = canManagePlatformConfig(user);
  const showOperatorDashboard = canAccessOperatorDashboard(user);

  // Determine sidebar mode from route
  const isCommunityRoute = location.pathname.startsWith("/c/");
  // The community directory brings its own: what narrows it belongs beside the
  // cards it narrows, not on the page with them. Only where there is a
  // directory to narrow, though — where the owner runs none, the page says so
  // and the sidebar stays the personal one, rather than offering a search and
  // twelve shelves that answer nothing. While the config is still loading the
  // directory gets the benefit of the doubt, so the two halves of the screen
  // arrive at the same answer at the same time.
  const isDirectoryRoute =
    location.pathname === "/communities" || location.pathname.startsWith("/communities/");
  const showDirectorySidebar = isDirectoryRoute && (communityDirectoryEnabled || configLoading);

  // Which project row to highlight. A project is addressed inside its
  // initiative, so the pattern has to carry that segment too.
  const activeProjectId = useMemo(() => {
    const match = location.pathname.match(/^\/c\/\d+\/i\/\d+\/projects\/(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }, [location.pathname]);

  // The wiki the reader is inside, and the page they are on. A wiki takes the
  // sidebar over the way My Messages does — a wiki is a list of pages and then
  // one of them, which is two levels in a column with room for one.
  const openWiki = useMemo(() => {
    const match = location.pathname.match(/^\/c\/\d+\/i\/(\d+)\/wikis\/(\d+)/);
    if (!match) return null;
    const page = location.pathname.match(/\/wikis\/\d+\/pages\/(\d+)/);
    return {
      initiativeId: parseInt(match[1], 10),
      wikiId: parseInt(match[2], 10),
      pageId: page ? parseInt(page[1], 10) : null,
    };
  }, [location.pathname]);

  // Climbing out is a per-visit choice, not a stored one: leaving the wiki's
  // URL puts the ordinary navigation back on its own.
  const [climbedOutOfWiki, setClimbedOutOfWiki] = useState(false);
  useEffect(() => setClimbedOutOfWiki(false), [openWiki?.wikiId]);
  const showWikiSidebar = openWiki !== null && !climbedOutOfWiki;

  // Helper to create community-scoped paths
  const gp = (path: string) => (activeCommunityId ? communityPath(activeCommunityId, path) : path);

  // The community tree (initiatives/projects/files/queues/counters/tags) is
  // only rendered on /c/ routes, and only there does the server-held community
  // context line up with it — on personal pages these community-scoped queries
  // would 409 (no context) and cache errors that linger as zeroed counts.
  // Gate them all on actually being in the community UI.
  const communityTreeEnabled = Boolean(activeCommunity) && isCommunityRoute;

  const initiativesQuery = useInitiatives({ enabled: communityTreeEnabled, staleTime: 60_000 });

  // What the community offers to join, which is what decides whether the "browse"
  // row is worth a line: with an empty directory it would lead nowhere.
  const directoryQuery = useInitiativeDirectory({
    enabled: communityTreeEnabled,
    staleTime: 60_000,
  });

  // The slim projection carries everything a row reads (id, name, icon,
  // initiative, archived state, `can`) without the per-project summaries.
  const projectsQuery = useProjects(
    { slim: true, ...toolViewParams(Tool.project, "active") },
    {
      enabled: communityTreeEnabled,
      staleTime: 60_000,
    }
  );

  // The reader's bookmarks here, every kind of tool, newest first.
  const bookmarksQuery = useCommunityBookmarks(null, {
    enabled: communityTreeEnabled,
    staleTime: 60_000,
  });
  // Which of them is open: the tool the address names.
  const activeTool = useMemo(() => getActiveRecentKey(location.pathname), [location.pathname]);

  // Every tool's per-initiative counts in one fan-out, keyed by `Tool`, so
  // the badges follow the registry rather than a list kept in step by hand.
  const toolCounts = useToolCountsByInitiative({
    enabled: communityTreeEnabled,
    staleTime: 60_000,
  });

  // One tool's badge per initiative, in the registry's terms. Projects count
  // the list that expands directly beneath that row rather than the server's
  // total, so the badge and the rows under it agree.
  const countsFor = (initiativeId: number, projectCount: number): Record<Tool, number> => {
    const counts = {} as Record<Tool, number>;
    for (const tool of TOOLS) {
      counts[tool] = toolCounts[tool].counts.get(initiativeId) ?? 0;
    }
    counts[Tool.project] = projectCount;
    return counts;
  };

  const projectsByInitiative = useMemo(() => {
    const map = new Map<number, ProjectRead[]>();
    const projects = projectsQuery.data?.items ?? [];
    projects.forEach((project) => {
      if (project.archived_at === null) {
        const existing = map.get(project.initiative_id) ?? [];
        map.set(project.initiative_id, [...existing, project]);
      }
    });
    return map;
  }, [projectsQuery.data]);

  const visibleInitiatives = useMemo(
    () => liveInitiatives(Array.isArray(initiativesQuery.data) ? initiativesQuery.data : []),
    [initiativesQuery.data]
  );

  // The same install list the Plug-ins section reads, handed to each initiative so
  // a plug-in declaring a surface in one gets a row there too. Filtered to what is
  // actually reachable, on the same terms the Plug-ins section uses.
  const communityPluginsQuery = useCommunityPlugins({ enabled: communityTreeEnabled });
  const initiativePlugins = useMemo(
    () =>
      (communityPluginsQuery.data?.items ?? []).filter(
        (plugin) => plugin.enabled && plugin.available !== false
      ),
    [communityPluginsQuery.data]
  );

  // Your own account, so your own name if you set one — and your handle, not
  // your address, when you have not.

  // Fetch tags for the tag browser
  const tagsQuery = useTags({ enabled: communityTreeEnabled });

  // Collapse/expand all for initiatives
  const [initiativeCollapseKey, setInitiativeCollapseKey] = useState(0);
  // Remembered like the other sections; open by default so a newly installed
  // plug-in is visible without hunting for it.
  const [pluginsOpen, setPluginsOpenState] = useState(
    () => getItem("plugins-section-open") !== "false"
  );
  const setPluginsOpen = (open: boolean) => {
    setPluginsOpenState(open);
    setItem("plugins-section-open", String(open));
  };
  const collapseAllInitiatives = useCallback(() => {
    const states: Record<number, boolean> = {};
    for (const init of visibleInitiatives) {
      states[init.id] = false;
    }
    setItem("initiative-collapsed-states", JSON.stringify(states));
    setInitiativeCollapseKey((k) => k + 1);
  }, [visibleInitiatives]);
  const expandAllInitiatives = useCallback(() => {
    const states: Record<number, boolean> = {};
    for (const init of visibleInitiatives) {
      states[init.id] = true;
    }
    setItem("initiative-collapsed-states", JSON.stringify(states));
    setInitiativeCollapseKey((k) => k + 1);
  }, [visibleInitiatives]);
  const allInitiativesCollapsed = useMemo(() => {
    try {
      const stored = getItem("initiative-collapsed-states");
      if (!stored) return false;
      const states = JSON.parse(stored) as Record<number, boolean>;
      return (
        visibleInitiatives.length > 0 && visibleInitiatives.every((i) => states[i.id] === false)
      );
    } catch {
      return false;
    }
  }, [visibleInitiatives, initiativeCollapseKey]);

  // Collapse/expand all for tags
  const [tagCollapseKey, setTagCollapseKey] = useState(0);
  const [tagEditMode, setTagEditMode] = useState(false);
  const collapseAllTags = useCallback(() => {
    setItem("tag-group-collapsed-states", JSON.stringify({}));
    setTagCollapseKey((k) => k + 1);
  }, []);
  const expandAllTags = useCallback(() => {
    const tags = tagsQuery.data ?? [];
    const states: Record<string, boolean> = {};
    for (const tag of tags) {
      if (tag.name.includes("/")) {
        // Expand all parent segments
        const parts = tag.name.split("/");
        let path = "";
        for (const part of parts.slice(0, -1)) {
          path = path ? `${path}/${part}` : part;
          states[path] = true;
        }
      }
    }
    setItem("tag-group-collapsed-states", JSON.stringify(states));
    setTagCollapseKey((k) => k + 1);
  }, [tagsQuery.data]);
  // Mirrors allInitiativesCollapsed: groups default collapsed, so the header
  // toggle shows "expand all" until some group path is stored open.
  const allTagsCollapsed = useMemo(() => {
    try {
      const stored = getItem("tag-group-collapsed-states");
      if (!stored) return true;
      const states = JSON.parse(stored) as Record<string, boolean>;
      return !Object.values(states).some(Boolean);
    } catch {
      return true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- storage-backed, re-read per collapse action
  }, [tagCollapseKey]);

  // Fetch the latest released version
  const { data: latestVersion, isLoading: isLoadingVersion } = useLatestVersion();
  const currentVersion = __APP_VERSION__;
  const hasUpdate =
    latestVersion && currentVersion && compareVersions(latestVersion, currentVersion) > 0;

  return (
    <Sidebar
      className="sticky top-0 h-dvh"
      variant="sidebar"
      collapsible={isMobile ? "offcanvas" : "none"}
    >
      <div className="flex h-full w-full min-w-0 max-w-full flex-col">
        <div className="flex min-h-0 max-w-full flex-1">
          <CommunitySidebar isHomeMode={!isCommunityRoute} />
          <div className="flex min-w-0 max-w-full flex-1 flex-col overflow-hidden border-r">
            {showDirectorySidebar ? (
              <CommunityDirectorySidebar />
            ) : showWikiSidebar && openWiki ? (
              <WikiSidebarContent
                wikiId={openWiki.wikiId}
                initiativeId={openWiki.initiativeId}
                activePageId={openWiki.pageId}
                onBack={() => setClimbedOutOfWiki(true)}
              />
            ) : !isCommunityRoute ? (
              <HomeSidebarContent />
            ) : (
              <>
                <SidebarHeader
                  className="gap-0 p-0"
                  style={{ paddingTop: "var(--safe-area-inset-top)" }}
                >
                  {/* The rule goes on the wrapper, not the h-12 row, so the
                      row is a full 3rem and the border sits below it — the
                      recents bar across the top of the page is built the same
                      way, and a border inside the box would leave the two 1px
                      out of line. */}
                  <div className="border-b">
                    <div className="flex h-12 min-w-0 items-center justify-between gap-2 px-2.5">
                      <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
                        {activeCommunity?.name ?? t("selectCommunity")}
                      </h2>
                      {activeCommunity && showsCommunitySettings && (
                        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" asChild>
                          <Link to={gp("/settings")} aria-label={t("communitySettings")}>
                            <Settings className="h-4 w-4" />
                          </Link>
                        </Button>
                      )}
                    </div>
                  </div>
                  <SidebarSearchButton communityName={activeCommunity?.name} />
                </SidebarHeader>

                <Tabs defaultValue="initiatives" className="flex flex-1 flex-col overflow-hidden">
                  {/* <div className="border-b px-2"> */}
                  <TabsBar className="h-9 rounded-none">
                    <TabsTrigger value="initiatives" className="text-xs">
                      <InitiativeMark className="mr-2 h-3.5 w-3.5" />
                      {t("initiatives")}
                    </TabsTrigger>
                    <TabsTrigger value="tags" className="text-xs">
                      <Tag className="mr-2 h-3.5 w-3.5" />
                      {t("tags")}
                    </TabsTrigger>
                  </TabsBar>
                  {/* </div> */}

                  <TabsContent value="initiatives" className="mt-0 flex-1 overflow-hidden">
                    <ScrollArea className="[&_[data-radix-scroll-area-viewport]>div]:block! h-full">
                      <SidebarContent className="overflow-x-hidden overflow-y-visible">
                        {/* Bookmarks */}
                        {Array.isArray(bookmarksQuery?.data) && bookmarksQuery.data.length > 0 && (
                          <>
                            <SidebarGroup>
                              <SidebarGroupLabel className="flex items-center gap-2 py-2">
                                <Bookmark className="h-4 w-4" />
                                {t("bookmarks")}
                              </SidebarGroupLabel>
                              <SidebarGroupContent>
                                <SidebarMenu>
                                  {bookmarksQuery.data.map((item) => (
                                    <SidebarMenuItem key={`${item.entity_type}:${item.entity_id}`}>
                                      <SidebarMenuButton
                                        asChild
                                        isActive={
                                          activeTool?.entityType === item.entity_type &&
                                          activeTool.entityId === item.entity_id
                                        }
                                      >
                                        <Link
                                          to={recentRoute(item)}
                                          className="flex min-w-0 items-center gap-2"
                                        >
                                          <span className="flex size-5 shrink-0 items-center justify-center">
                                            {renderRecentIcon(item)}
                                          </span>
                                          <span className="min-w-0 flex-1 truncate">
                                            {item.name}
                                          </span>
                                        </Link>
                                      </SidebarMenuButton>
                                    </SidebarMenuItem>
                                  ))}
                                </SidebarMenu>
                              </SidebarGroupContent>
                            </SidebarGroup>
                            <SidebarSeparator />
                          </>
                        )}

                        {/* Plug-ins: community-wide surfaces, so they sit above the
                            initiatives rather than inside any of them. */}
                        {activeCommunity && (
                          <>
                            <PluginsSection
                              isCommunityAdmin={isCommunityAdmin}
                              open={pluginsOpen}
                              onOpenChange={setPluginsOpen}
                            />
                            <SidebarSeparator />
                          </>
                        )}

                        {/* Initiatives Section */}
                        <SidebarGroup>
                          <SidebarGroupLabel className="flex items-center gap-2 py-2">
                            <InitiativeMark className="h-4 w-4" />
                            <span className="flex-1">{t("initiatives")}</span>
                            {visibleInitiatives.length > 0 && (
                              <Tooltip delayDuration={300}>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-5 w-5 shrink-0"
                                    onClick={
                                      allInitiativesCollapsed
                                        ? expandAllInitiatives
                                        : collapseAllInitiatives
                                    }
                                    aria-label={
                                      allInitiativesCollapsed ? t("expandAll") : t("collapseAll")
                                    }
                                  >
                                    {allInitiativesCollapsed ? (
                                      <ChevronsUpDown className="h-3.5 w-3.5" />
                                    ) : (
                                      <ChevronsDownUp className="h-3.5 w-3.5" />
                                    )}
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent side="bottom">
                                  <p>
                                    {allInitiativesCollapsed ? t("expandAll") : t("collapseAll")}
                                  </p>
                                </TooltipContent>
                              </Tooltip>
                            )}
                          </SidebarGroupLabel>
                          <SidebarGroupContent>
                            {initiativesQuery.isLoading ? (
                              <div className="space-y-2 px-4">
                                <Skeleton className="h-8 w-full" />
                                <Skeleton className="h-8 w-full" />
                                <Skeleton className="h-8 w-full" />
                              </div>
                            ) : visibleInitiatives.length === 0 ? (
                              <div className="px-4 py-2 text-muted-foreground text-sm">
                                {t("noInitiativesAvailable")}
                              </div>
                            ) : (
                              <div className="space-y-1">
                                {visibleInitiatives.map((initiative) => {
                                  const projects = projectsByInitiative.get(initiative.id) ?? [];
                                  return (
                                    <InitiativeSection
                                      key={initiative.id}
                                      initiative={initiative}
                                      projects={projects}
                                      activeProjectId={activeProjectId}
                                      plugins={initiativePlugins}
                                      counts={countsFor(initiative.id, projects.length)}
                                      activeCommunityId={activeCommunityId}
                                      collapseKey={initiativeCollapseKey}
                                    />
                                  );
                                })}
                              </div>
                            )}

                            <SidebarMenu>
                              {/* The way into an initiative you aren't in yet:
                                  community home carries the directory. Only shown
                                  when the community actually lists something. */}
                              {(directoryQuery.data?.length ?? 0) > 0 && (
                                <SidebarMenuItem>
                                  <SidebarMenuButton asChild size="sm">
                                    <Link to={gp("/")} hash={DIRECTORY_SECTION_ID}>
                                      <Binoculars className="h-4 w-4" />
                                      <span>{t("initiatives:directory.browse")}</span>
                                    </Link>
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                              )}
                              {createsInitiatives && (
                                <SidebarMenuItem>
                                  <SidebarMenuButton asChild size="sm">
                                    {/* The create dialog lives on community home
                                        with the rest of the initiative list. */}
                                    <Link to={gp("/")} search={{ create: "true" }}>
                                      <Plus className="h-4 w-4" />
                                      <span>{t("addInitiative")}</span>
                                    </Link>
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                              )}
                            </SidebarMenu>
                          </SidebarGroupContent>
                        </SidebarGroup>
                      </SidebarContent>
                    </ScrollArea>
                  </TabsContent>

                  <TabsContent value="tags" className="mt-0 flex-1 overflow-hidden">
                    <ScrollArea className="[&_[data-radix-scroll-area-viewport]>div]:block! h-full">
                      <SidebarContent className="overflow-x-hidden overflow-y-visible">
                        <SidebarGroup>
                          <SidebarGroupLabel className="flex items-center gap-2 py-2">
                            <Tag className="h-4 w-4" />
                            <span className="flex-1">{t("tags")}</span>
                            {(tagsQuery.data ?? []).length > 0 && (
                              <>
                                <Tooltip delayDuration={300}>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-5 w-5 shrink-0"
                                      onClick={() => setTagEditMode((v) => !v)}
                                      aria-pressed={tagEditMode}
                                      aria-label={
                                        tagEditMode ? t("tags:manage.done") : t("tags:manage.edit")
                                      }
                                    >
                                      {tagEditMode ? (
                                        <Check className="h-3.5 w-3.5" />
                                      ) : (
                                        <Pencil className="h-3.5 w-3.5" />
                                      )}
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="bottom">
                                    <p>
                                      {tagEditMode ? t("tags:manage.done") : t("tags:manage.edit")}
                                    </p>
                                  </TooltipContent>
                                </Tooltip>
                                <Tooltip delayDuration={300}>
                                  <TooltipTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-5 w-5 shrink-0"
                                      onClick={allTagsCollapsed ? expandAllTags : collapseAllTags}
                                      aria-label={
                                        allTagsCollapsed ? t("expandAll") : t("collapseAll")
                                      }
                                    >
                                      {allTagsCollapsed ? (
                                        <ChevronsUpDown className="h-3.5 w-3.5" />
                                      ) : (
                                        <ChevronsDownUp className="h-3.5 w-3.5" />
                                      )}
                                    </Button>
                                  </TooltipTrigger>
                                  <TooltipContent side="bottom">
                                    <p>{allTagsCollapsed ? t("expandAll") : t("collapseAll")}</p>
                                  </TooltipContent>
                                </Tooltip>
                              </>
                            )}
                          </SidebarGroupLabel>
                          <SidebarGroupContent>
                            <TagBrowser
                              tags={tagsQuery.data ?? []}
                              isLoading={tagsQuery.isLoading}
                              activeCommunityId={activeCommunityId}
                              collapseKey={tagCollapseKey}
                              editMode={tagEditMode}
                              onExpandAll={expandAllTags}
                            />
                          </SidebarGroupContent>
                        </SidebarGroup>
                      </SidebarContent>
                    </ScrollArea>
                  </TabsContent>
                </Tabs>
              </>
            )}
          </div>
        </div>

        <SidebarUserFooter
          user={user}
          canManagePlatformConfig={showPlatformSettings}
          canAccessOperatorDashboard={showOperatorDashboard}
          currentVersion={currentVersion}
          latestVersion={latestVersion ?? null}
          hasUpdate={Boolean(hasUpdate)}
          isLoadingVersion={isLoadingVersion}
          onLogout={logout}
          refreshUser={refreshUser}
        />
      </div>
    </Sidebar>
  );
};
