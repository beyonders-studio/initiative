import { Link, Navigate, useParams } from "@tanstack/react-router";
import { Info, SearchX, Settings } from "lucide-react";
import { type ComponentType, type CSSProperties, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeMembersPeek } from "@/components/initiatives/InitiativeMembersPeek";
import { Markdown } from "@/components/Markdown";
import { StatusMessage } from "@/components/StatusMessage";
import {
  InitiativePageSkeleton,
  SkeletonRegion,
  ToolListSkeleton,
} from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useCommunities } from "@/hooks/useCommunities";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { resolveInitiativeColor } from "@/lib/initiativeColors";
import { initiativeRoute, TOOLS, toolCamelPlural, toolListRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

import { CounterGroupsView } from "./initiativeTools/counters/CounterGroupsPage";
import { DashboardsView } from "./initiativeTools/dashboards/DashboardsPage";
import { CalendarsView } from "./initiativeTools/events/CalendarsPage";
import { FilesView } from "./initiativeTools/files/FilesPage";
import { PostsView } from "./initiativeTools/posts/PostsPage";
import { ProjectsView } from "./initiativeTools/projects/ProjectsPage";
import { QueuesView } from "./initiativeTools/queues/QueuesPage";
import { WikisView } from "./initiativeTools/wikis/WikisPage";

type ToolViewProps = { fixedInitiativeId: number; canCreate: boolean };

// Each tool's list view. A new tool adds one line here (the drift test
// asserts every tool has an entry); the tab ORDER is not restated — it is the
// registry's canonical order, so these tabs read in the same sequence as the
// community home's tool rail.
const TOOL_VIEWS: Record<Tool, ComponentType<ToolViewProps>> = {
  [Tool.project]: ProjectsView,
  [Tool.file]: FilesView,
  [Tool.queue]: QueuesView,
  [Tool.counter_group]: CounterGroupsView,
  [Tool.calendar]: CalendarsView,
  [Tool.dashboard]: DashboardsView,
  [Tool.post]: PostsView,
  [Tool.wiki]: WikisView,
};

const TOOL_TABS: Array<[Tool, ComponentType<ToolViewProps>]> = TOOLS.map((tool) => [
  tool,
  TOOL_VIEWS[tool],
]);

export const TOOL_TAB_VIEWS: ReadonlyMap<Tool, ComponentType<ToolViewProps>> = new Map(TOOL_TABS);

export interface InitiativeDetailPageProps {
  /** The tool tab the URL names. Omitted on the bare initiative route, where
   *  the page falls back to the first tab this member can see. */
  tool?: Tool;
}

export const InitiativeDetailPage = ({ tool }: InitiativeDetailPageProps = {}) => {
  const { initiativeId: initiativeIdParam } = useParams({
    strict: false,
  }) as {
    initiativeId: string;
  };
  const gp = useCommunityPath();
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeCommunity } = useCommunities();
  const communityAdminLabel = t("settings.communityAdminRole");

  // Addressed by id, not picked out of the caller's own list: a community admin
  // reaches every initiative in their community whether or not they have joined it,
  // and the endpoint answers 404 to anyone the row is not visible to.
  const initiativeQuery = useInitiative(hasValidInitiativeId ? initiativeId : null);
  const initiative = initiativeQuery.data ?? null;
  const isCommunityAdmin = Boolean(activeCommunity?.can.administer_content);
  const canManageInitiative = Boolean(initiative?.can.manage);

  // A tool's tab renders when its permission allows viewing it (the backend
  // already folds in the initiative's master switches). The advanced tool is
  // additionally gated by the deployment-level runtime config.
  const availableTabs = useMemo<Tool[]>(
    () =>
      TOOL_TABS.map(([tabTool]) => tabTool).filter((tabTool) =>
        Boolean(initiative?.can.view.includes(tabTool))
      ),
    [initiative]
  );

  // The path names the tab, so it is shareable and survives a reload. A tool
  // this member can't view falls back to the first one they can, rather than
  // dead-ending a bookmark the moment a permission changes — the same rule My
  // Tools applies to its `?tool=` param.
  const activeTab =
    tool && availableTabs.includes(tool) ? tool : (availableTabs[0] ?? Tool.project);

  const memberCount = initiative?.member_count ?? 0;

  const [descriptionOpen, setDescriptionOpen] = useState(false);

  const roleBadgeLabel =
    initiative?.role_display_name ?? (isCommunityAdmin ? communityAdminLabel : null);

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/")} replace />;
  }

  if (initiativeQuery.isLoading) {
    return <InitiativePageSkeleton label={t("detail.loadingInitiative")} />;
  }

  if (!initiative) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo={gp("/")}
        backLabel={t("detail.backToInitiatives")}
      />
    );
  }

  const color = resolveInitiativeColor(initiative.color);

  // If user has no access to any features, show a message
  if (availableTabs.length === 0) {
    return (
      <div className="space-y-6">
        <div className="border-l-2 pl-4" style={{ borderColor: color }}>
          <h1 className="font-semibold text-3xl tracking-tight">{initiative.name}</h1>
          <p className="mt-2 text-muted-foreground">{t("detail.noAccess")}</p>
        </div>
      </div>
    );
  }

  // Local Suspense fallback for tab content — keeps the placeholder below the
  // tabs while a lazily-loaded i18n namespace (queues/events/counters)
  // resolves, instead of letting the suspension bubble up to a full-page
  // fallback.
  const tabFallback = (
    <SkeletonRegion className="mt-6">
      <ToolListSkeleton />
    </SkeletonRegion>
  );

  const description = initiative.description ? (
    <Markdown content={initiative.description} className="text-muted-foreground" />
  ) : null;

  return (
    <div className="space-y-6">
      {/* The header is context, not content. On a phone it is the title, the
          settings gear and who is here; the description sits one tap away
          rather than pushing the tool's list off screen. The row never wraps —
          a long name wraps its own text instead (it can shrink past its
          content, hence min-w-0), so the gear stays put. */}
      <div className="flex items-start justify-between gap-4">
        {/* The initiative's colour as a rule down the side of its name: the
            line the sidebar draws under the same initiative's tools. */}
        <div className="min-w-0 flex-1 border-l-2 pl-4" style={{ borderColor: color }}>
          <div className="flex items-start gap-1">
            <h1 className="min-w-0 break-words font-semibold text-3xl tracking-tight">
              {initiative.name}
            </h1>
            {/* On a phone the description waits behind a small toggle beside
                the name, so it costs no row until somebody asks for it. */}
            {description ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className={cn(
                  "mt-1.5 h-6 w-6 shrink-0 rounded-full text-muted-foreground sm:hidden",
                  descriptionOpen && "bg-accent text-foreground"
                )}
                aria-expanded={descriptionOpen}
                aria-label={t("common:description")}
                onClick={() => setDescriptionOpen((open) => !open)}
              >
                <Info className="h-3.5 w-3.5" />
              </Button>
            ) : null}
          </div>
          {description ? (
            <div className={cn("mt-2 sm:block", !descriptionOpen && "hidden")}>{description}</div>
          ) : null}
          {/* One quiet line: the reader's role here, then who else is. Words in
              a row rather than a pill and a count strip, shown at every width:
              who is here is the point of the place. */}
          <p className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-muted-foreground text-sm">
            {roleBadgeLabel ? (
              <>
                <span>{roleBadgeLabel}</span>
                <span aria-hidden>·</span>
              </>
            ) : null}
            {/* A guest given items here reads its headcount and nobody in it. */}
            {initiative.can.roster ? (
              <InitiativeMembersPeek initiativeId={initiative.id} memberCount={memberCount} />
            ) : (
              <span>{t("detail.member", { count: memberCount })}</span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {canManageInitiative ? (
            <Button
              variant="outline"
              // Icon-only on a phone: the gear is unambiguous next to a title,
              // and the label is the widest thing in the header row.
              className="max-sm:h-9 max-sm:w-9 max-sm:p-0"
              asChild
            >
              <Link
                to={gp(`${initiativeRoute(initiative.id)}/settings`)}
                aria-label={t("detail.initiativeSettings")}
              >
                <Settings className="h-4 w-4" />
                <span className="hidden sm:inline">{t("detail.initiativeSettings")}</span>
              </Link>
            </Button>
          ) : null}
        </div>
      </div>

      <Tabs value={activeTab}>
        {/* Words on a rule rather than a pill bar, the open one underlined in
            the initiative's colour — the same colour as the rule by its name. */}
        <TabsBar
          className="h-auto gap-5 rounded-none border-b bg-transparent p-0"
          style={{ "--initiative": color } as CSSProperties}
        >
          {TOOL_TABS.filter(([tabTool]) => availableTabs.includes(tabTool)).map(([tabTool]) => (
            <TabsTrigger
              key={tabTool}
              value={tabTool}
              className="-mb-px rounded-none border-transparent border-b-2 px-0 pt-1 pb-2 data-[state=active]:border-(--initiative) data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              asChild
            >
              {/* A real link, so a tab is shareable and answers the back
                    button. `search={{}}` clears the page cursor: all six tabs
                    now share one search schema, so a ?page from the queue tab
                    would otherwise follow the reader into files. */}
              <Link to={gp(toolListRoute(tabTool, initiative.id))} search={{}}>
                {t(`detail.${toolCamelPlural(tabTool)}` as never)}
              </Link>
            </TabsTrigger>
          ))}
        </TabsBar>
        {TOOL_TABS.filter(([tabTool]) => availableTabs.includes(tabTool)).map(([tabTool, View]) => (
          <TabsContent key={tabTool} value={tabTool} className="mt-6">
            <Suspense fallback={tabFallback}>
              <View
                key={`${tabTool}-${initiative.id}`}
                fixedInitiativeId={initiative.id}
                canCreate={initiative.can.create.includes(tabTool)}
              />
            </Suspense>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
};
