/**
 * The community front page: what people changed lately in a tray under its
 * banner, one view per circle, then its initiatives and what is coming up.
 *
 * It is also the community's initiative list — the standalone initiatives page was
 * folded into it. The section under the tray holds the ones you're in and the
 * ones you could join, plus the create affordance for a community admin, and it
 * takes the page over entirely for a member who is not yet in any initiative,
 * for whom every other section is empty by construction.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Activity, MessageSquare, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { FeedView } from "@/api/generated/initiativeAPI.schemas";
import { CatchUpButton } from "@/components/activity/CatchUpButton";
import { CommunityLocationLine } from "@/components/communities/CommunityLocationLine";
import { CommunityActivityFeed } from "@/components/communityHome/CommunityActivityFeed";
import { CommunityBannerBadges } from "@/components/communityHome/CommunityBannerBadges";
import { CommunityComingUp } from "@/components/communityHome/CommunityComingUp";
import { CommunityHomeEmptyState } from "@/components/communityHome/CommunityHomeEmptyState";
import { CommunityRecentComments } from "@/components/communityHome/CommunityRecentComments";
import { InitiativeDirectory } from "@/components/communityHome/InitiativeDirectory";
import { CreateInitiativeWizard } from "@/components/initiatives/CreateInitiativeWizard";
import { PageBanner } from "@/components/PageBanner";
import { PluginSettingsDialog } from "@/components/plugins/PluginSettingsDialog";
import { NodeRail, TRAY_SURFACE } from "@/components/toolBrowser/NodeRail";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { liveInitiatives, useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiativeDirectory, useInitiatives } from "@/hooks/useInitiatives";
import { useLastVisit } from "@/hooks/useLastVisit";
import { activityLastVisitKey } from "@/lib/activityLastVisit";
import { renderableBanner } from "@/lib/banner";
import { useCommunityPath } from "@/lib/communityUrl";
import { readableTextShadow } from "@/lib/contrastColor";
import { cn } from "@/lib/utils";

/** The rail's circles, in order; the first is the default. All and Yours are
 *  views of the activity feed; Comments shows the comments themselves. */
const FEED_NODES = [
  { view: FeedView.all, icon: Activity },
  { view: FeedView.yours, icon: UserRound },
  { view: FeedView.comments, icon: MessageSquare },
] as const;

const isFeedView = (value: unknown): value is FeedView =>
  FEED_NODES.some((node) => node.view === value);

export function CommunityHomePage() {
  const { t } = useTranslation("communityHome");
  const { activeCommunity } = useCommunities();
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as {
    create?: string;
    plugin?: number;
    node?: string;
  };
  const view = isFeedView(search.node) ? search.node : FeedView.all;
  const communityId = useActiveCommunityId();
  const { user } = useAuth();
  const lastVisit = useLastVisit(user ? activityLastVisitKey(user.id, communityId) : null);

  const initiativesQuery = useInitiatives();
  const directoryQuery = useInitiativeDirectory();
  const directoryEntries = directoryQuery.data ?? [];
  const { isCommunityAdmin } = useInitiativeAccess();

  // Creating an initiative is community-admin only (the backend enforces it), and
  // the affordance is threaded down as a callback: passing one IS the gate.
  const canCreateInitiatives = Boolean(activeCommunity && isCommunityAdmin);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const openCreateDialog = useCallback(() => setCreateDialogOpen(true), []);
  const onCreate = canCreateInitiatives ? openCreateDialog : undefined;

  // `?create=true` opens the dialog once — the deep link the sidebar and the
  // retired initiatives page both point at. Consumed once so dismissing the
  // dialog doesn't reopen it on the next render.
  const lastConsumedCreate = useRef<string>("");
  useEffect(() => {
    const shouldCreate = search.create === "true";
    const paramKey = `${shouldCreate}`;
    if (shouldCreate && paramKey !== lastConsumedCreate.current) {
      lastConsumedCreate.current = paramKey;
      setCreateDialogOpen(true);
    }
  }, [search.create]);

  const visibleInitiatives = useMemo(
    () => liveInitiatives(initiativesQuery.data),
    [initiativesQuery.data]
  );

  // Nothing to see: every section would be empty, so the page becomes the
  // story of how to get in instead. Only an answered query can say "none" — a
  // failed or still-arriving one is absence of news, and telling someone
  // they're in nothing on that basis would be a lie the page states confidently.
  const hasNoInitiatives = initiativesQuery.isSuccess && visibleInitiatives.length === 0;

  const railNodes = useMemo(
    () =>
      FEED_NODES.map(({ view, icon }) => ({
        segment: view,
        icon,
        label: t(`feed.nodes.${view}`),
      })),
    [t]
  );

  // Every community has a banner — the artwork it uploaded, or the colour it wears
  // instead — so this is the community's header rather than a decoration it might
  // be without. A community with no artwork gets a short band, not a hero.
  const banner = renderableBanner(activeCommunity?.banner);

  // A faded banner is extended past where it would have ended, and the page's
  // own content is pulled back over the tail — so everything below the banner
  // needs to be positioned to paint over it, which a plain block would not.
  return (
    <div className="space-y-6">
      <PageBanner
        banner={banner}
        title={activeCommunity?.name ?? t("title")}
        subtitle={activeCommunity?.description ?? t("subtitle")}
        meta={
          activeCommunity?.location ? (
            <CommunityLocationLine
              location={activeCommunity.location}
              className="font-medium text-sm sm:text-base"
              style={{
                color: banner.text_color,
                textShadow: readableTextShadow(banner.text_color),
              }}
            />
          ) : null
        }
        badges={
          activeCommunity ? (
            <CommunityBannerBadges
              communityId={activeCommunity.id}
              memberCount={activeCommunity.member_count}
              onlineCount={activeCommunity.online_count}
              ink={banner.text_color}
            />
          ) : null
        }
      />

      <div className="relative z-10 space-y-6">
        {hasNoInitiatives ? (
          <CommunityHomeEmptyState
            entries={directoryEntries}
            directoryStatus={
              directoryQuery.isSuccess ? "success" : directoryQuery.isError ? "error" : "pending"
            }
            onCreate={onCreate}
          />
        ) : (
          <>
            {/* The rail and the feed are one tray: the circles are its top
                edge rising, and what the open one shows sits in the same
                surface underneath it. */}
            <div>
              <NodeRail
                nodes={railNodes}
                selected={view}
                to={gp("/")}
                param="node"
                label={t("nodeRail")}
                align={banner.text_align}
              />
              <div className={cn("rounded-b-2xl p-3 sm:px-4 sm:pb-4", TRAY_SURFACE)}>
                {view === FeedView.comments ? (
                  <CommunityRecentComments />
                ) : (
                  <>
                    <div className="mb-2 flex justify-end">
                      <CatchUpButton since={lastVisit} />
                    </div>
                    <CommunityActivityFeed view={view} lastVisit={lastVisit} />
                  </>
                )}
              </div>
            </div>

            {/* The community's initiative list, which is also its discovery surface:
              the ones you're in, then the ones you could join. */}
            <InitiativeDirectory entries={directoryEntries} onCreate={onCreate} />

            {/* The week ahead, community-wide. */}
            <CommunityComingUp />
          </>
        )}

        {/* `?plugin=` opens one plug-in's settings where the reader answers what it
            asked to do as them — the link its notification carries. */}
        {search.plugin ? (
          <PluginSettingsDialog
            pluginId={search.plugin}
            isCommunityAdmin={isCommunityAdmin}
            open
            onOpenChange={(next) => {
              if (!next) {
                void navigate({ to: ".", search: { ...search, plugin: undefined }, replace: true });
              }
            }}
          />
        ) : null}

        {canCreateInitiatives ? (
          <CreateInitiativeWizard
            open={createDialogOpen}
            onOpenChange={setCreateDialogOpen}
            // The community's first: the wizard has to say what an initiative
            // is before it asks for a name. Read off the whole list, not the
            // visible one — an admin sees everything, and an archived
            // initiative still means somebody has been here before.
            isFirst={initiativesQuery.isSuccess && (initiativesQuery.data?.length ?? 0) === 0}
          />
        ) : null}
      </div>
    </div>
  );
}
