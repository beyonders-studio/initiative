import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
  useLocation,
  useMatches,
} from "@tanstack/react-router";
import { Loader2, LogOut, Settings, UserCog } from "lucide-react";
import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";

import { type RecentItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { AcceptTerms } from "@/components/AcceptTerms";
import { AccountTimeOut } from "@/components/AccountTimeOut";
import { AppSidebar } from "@/components/AppSidebar";
import { AnnouncementCenter } from "@/components/announcements/AnnouncementCenter";
import { UpdateAnnouncementDialog } from "@/components/announcements/UpdateAnnouncementDialog";
import { ChooseHandle } from "@/components/ChooseHandle";
import { CommandCenter } from "@/components/CommandCenter";
import { ConfirmBirthdate } from "@/components/ConfirmBirthdate";
import { CommunityAccessBanner } from "@/components/communities/CommunityAccessBanner";
import { DemoBannerOrTabs } from "@/components/demo/DemoBanner";
import { DeviceVerificationDialog } from "@/components/messages/DeviceVerificationDialog";
import { BottomNav } from "@/components/navigation/BottomNav";
import { CreateActionProvider } from "@/components/navigation/CreateActionContext";
import { PushPermissionPrompt } from "@/components/notifications/PushPermissionPrompt";
import { OfflineBanner } from "@/components/offline/OfflineBanner";
import { ProjectActivitySidebar } from "@/components/projects/ProjectActivitySidebar";
import { RecentTabsBar } from "@/components/recents/RecentTabsBar";
import { PageSkeleton } from "@/components/skeletons/PageSkeletons";
import { StartFlow } from "@/components/start/StartFlow";
import { CreateTaskWizard } from "@/components/tasks/CreateTaskWizard";
import { FeedbackHost } from "@/components/tickets/FeedbackSheet";
import { CreateToolWizard } from "@/components/tools/CreateToolWizard";
import { Button } from "@/components/ui/button";
import { DocumentOutlineScope } from "@/components/ui/editor/DocumentOutline";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useAuth } from "@/hooks/useAuth";
import { useBackButton } from "@/hooks/useBackButton";
import { useCommunities } from "@/hooks/useCommunities";
import { useDesktopApp } from "@/hooks/useDesktopApp";
import { useFinishPendingStart } from "@/hooks/useFinishPendingStart";
import { useCollectMessagesWhereRegistered } from "@/hooks/useMyMessages";
import { useNotificationStream } from "@/hooks/useNotificationStream";
import { usePushNotifications } from "@/hooks/usePushNotifications";
import { useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import {
  type ClearRecentTarget,
  useClearRecentView,
  useClearRecentViews,
  useRecents,
} from "@/hooks/useRecents";
import { useVersionCheck } from "@/hooks/useVersionCheck";
import { isJustSignedIn } from "@/lib/authTransition";
import { chooseNoCommunityLayout } from "@/lib/noCommunityLayout";
import { canAccessPlatformAreas } from "@/lib/permissions";
import { getActiveRecentKey } from "@/lib/recentRoute";
import { returnPath } from "@/lib/returnPath";
import { cn } from "@/lib/utils";

/**
 * Loading fallback for lazy-loaded pages inside the main layout.
 */
const PageLoader = () => <PageSkeleton />;

/**
 * Full-screen loading state shown while auth is being determined.
 */
const FullScreenLoader = () => (
  <div className="flex min-h-screen items-center justify-center">
    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
  </div>
);

export const Route = createFileRoute("/_serverRequired/_authenticated")({
  beforeLoad: ({ context, location }) => {
    const { auth, server } = context;

    // If auth state is already determined and user is not authenticated,
    // redirect immediately (this handles direct navigation when auth is
    // cached). Skip during the brief just-signed-in window, when the auth
    // context hasn't committed the new user yet; logout clears the marker,
    // so a signed-out session always redirects.
    if (!isJustSignedIn() && !auth?.loading && !auth?.user) {
      const redirectTo = server?.isNativePlatform ? "/login" : "/welcome";
      // Carry where they were headed, so signing in finishes the trip they
      // started rather than landing them at the front page: the app sends a
      // phone to a browser for a passkey, and that browser signs in first.
      // Somewhere in this app only — a path, never another site.
      const next = returnPath(location.href);
      const carry = next && next !== "/" ? { next } : undefined;
      throw redirect({ to: redirectTo, search: carry });
    }
  },
  component: AuthenticatedLayout,
});

/**
 * A suspended account signs in to its time-out screen and nothing else. Decided
 * here, ahead of the app shell, so none of the shell's own requests — the
 * realtime stream, recents, messages — are made for an account that would be
 * refused every one of them.
 */
function AuthenticatedLayout() {
  const { user, loading } = useAuth();
  if (!loading && user?.status === "suspended") {
    return <AccountTimeOut />;
  }
  return <AppLayout />;
}

function AppLayout() {
  // ALL hooks must be called before any conditional returns
  const { user, loading, logout } = useAuth();
  const { communities, loading: communitiesLoading } = useCommunities();
  // Set while the start flow is making a community, so it stays on screen
  // once the account has one rather than giving way to the app shell.
  const [startFlowBusy, setStartFlowBusy] = useState(false);
  useFinishPendingStart();
  const location = useLocation();
  // Whether the route on screen lays itself out against the window. Read off
  // the matched routes rather than the path, so a route says it once where it
  // is declared.
  const fullBleed = useMatches({
    select: (matches) => matches.some((match) => match.staticData?.fullBleed === true),
  });
  const { updateAvailable, closeDialog } = useVersionCheck();

  useRealtimeUpdates();
  // Personal, cross-community, and mounted here rather than beside the bell so it
  // survives the bell unmounting with a collapsed sidebar.
  useNotificationStream();
  usePushNotifications();
  useDesktopApp();
  useBackButton();
  // Mail is fetched wherever you are, so a message that arrives while you are
  // on another page is noticed rather than waiting to be discovered. Only for a
  // browser that has already been set up for messages — this never sets one up.
  useCollectMessagesWhereRegistered();

  // No cross-tab community convergence: each tab keeps the community from its own URL,
  // so two tabs can sit in two different communities at once.

  // The tabs bar is cross-community by design (names only): one user-context
  // query, valid in any community and in personal mode.
  // A demo visitor's banner takes the tabs' row, so it has no use for them.
  const recentQuery = useRecents({
    enabled: !loading && !!user && !user.demo_expires_at,
    staleTime: 30_000,
  });

  const clearRecent = useClearRecentView();
  const clearRecents = useClearRecentViews();

  // An account that was handed its handle rather than picking one chooses
  // here, before anything else: it is how everyone else will see them.
  if (!loading && user && !user.username_chosen) {
    return <ChooseHandle />;
  }

  // Never agreed to this deployment's terms, on a deployment that has some.
  // Signing up through the form is the agreement and is recorded there, so
  // this is the way in that had no form: an account an identity provider
  // provisioned on first sign-in.
  if (!loading && user && user.legal_acceptance_required) {
    return <AcceptTerms />;
  }

  // No date of birth on file, on a deployment that checks age. Asked once of
  // every account — plug-ins can have a minimum age that differs by country —
  // and never again once answered. The server says when it is owed.
  if (!loading && user && user.birthdate_required) {
    return <ConfirmBirthdate />;
  }

  // Now we can have conditional returns
  // Show loading state while auth or community membership is being determined
  if (loading || communitiesLoading) {
    return <FullScreenLoader />;
  }

  // Not authenticated: the redirect belongs to `beforeLoad` above, which
  // re-runs as soon as the auth context settles (``useRouteGuardSync``). Hold
  // the loader for the render or two before that lands rather than redirecting
  // from the render path — a rendered `<Navigate>` re-navigates on every render
  // and stops only because this layout unmounts. The just-signed-in window
  // covers the render before the auth context commits the new user; logout
  // clears it, so signing out always leaves the authenticated shell.
  if (!user && !isJustSignedIn()) {
    return <FullScreenLoader />;
  }

  // No-community empty-state branch. The user-scoped settings routes
  // (``/profile/*``) and the platform areas (``/settings/operator/*`` and
  // ``/settings/platform/*``, for platform staff) don't need community context —
  // the APIs they call work without a server-held community — and a user with zero
  // memberships would otherwise have no path to delete their account
  // or, for platform staff, configure system-wide settings. The
  // path-based decision lives in ``chooseNoCommunityLayout`` so it can be
  // unit-tested without a router; see ``noCommunityLayout.test.ts``.
  if (user) {
    const reachesPlatformAreas = canAccessPlatformAreas(user);
    const layout = chooseNoCommunityLayout({
      hasCommunities: communities.length > 0,
      pathname: location.pathname,
      canAccessPlatformAreas: reachesPlatformAreas,
    });
    if (layout === "empty" || startFlowBusy) {
      return (
        <NoCommunityState
          logout={logout}
          reachesPlatformAreas={reachesPlatformAreas}
          onBusy={setStartFlowBusy}
        />
      );
    }
    if (layout === "shell") {
      return <NoCommunitySettingsShell logout={logout} />;
    }
    // layout === "main" → fall through to the standard sidebar layout.
  }

  const toClearTarget = (item: RecentItemRead): ClearRecentTarget => ({
    entityType: item.entity_type,
    entityId: item.entity_id,
    communityId: item.community_id,
  });

  const handleClearRecent = (item: RecentItemRead) => {
    clearRecent.mutate(toClearTarget(item));
  };

  const handleCloseOtherRecents = (keep: RecentItemRead) => {
    const others = (recentQuery.data ?? []).filter(
      (item) =>
        !(
          item.community_id === keep.community_id &&
          item.entity_type === keep.entity_type &&
          item.entity_id === keep.entity_id
        )
    );
    if (others.length > 0) {
      clearRecents.mutate(others.map(toClearTarget));
    }
  };

  const handleCloseAllRecents = () => {
    const all = recentQuery.data ?? [];
    if (all.length > 0) {
      clearRecents.mutate(all.map(toClearTarget));
    }
  };

  // The backend already caps the list to the user's ``recent_tabs_limit``, but
  // slice client-side too so lowering the setting takes effect immediately
  // (before the 30s-stale recents query refetches).
  const recentItems = recentQuery.data?.slice(0, user?.recent_tabs_limit ?? 20);

  const activeRecentKey = getActiveRecentKey(location.pathname);
  // ProjectActivitySidebar still wants the active project directly — and the
  // initiative it sits in, since a task's URL names that too.
  const activeProjectId =
    activeRecentKey?.entityType === Tool.project ? activeRecentKey.entityId : null;
  const activeProjectInitiativeId =
    activeRecentKey?.entityType === Tool.project ? activeRecentKey.initiativeId : null;

  // const isDark = document.documentElement.classList.contains("dark");

  return (
    <CreateActionProvider>
      <CommandCenter />
      <FeedbackHost />
      <CreateTaskWizard />
      <CreateToolWizard tool={Tool.file} />
      {/* A real height rather than a minimum: `min-h-screen` leaves every
          descendant sizing to its own content, so a page cannot ask for the
          height of what it is in. Scrolling moves from the document into
          `main` with it -- which is what lets a page keep a header or a
          composer against an edge instead of measuring where that edge fell. */}
      {/* `clip` rather than `hidden`: both hide what overruns, but `hidden`
          leaves a scrollport behind -- one with no scrollbar, which a reader
          cannot get back from and which anything at all can move. Focus moving
          to a grown textarea, a `scrollIntoView`, a devtools panel in the flow:
          each parks the whole app, chrome included, somewhere it cannot be
          scrolled back from. `clip` makes it what it reads as: not a scroller. */}
      {/* `relative`, so that this box is the containing block for anything
          absolutely positioned with no nearer positioned ancestor. A clip only
          applies to descendants whose containing-block chain runs through it;
          the rest are laid out against the document, and it is the document
          that grows to fit them. */}
      <div className="relative flex h-dvh flex-col overflow-clip bg-background">
        <DeviceVerificationDialog />
        <div className="flex min-h-0 flex-1">
          {/* The live editor's headings, shared by the page that hosts the
              editor and the sidebar beside it — a wiki lists a page's headings
              under the page. The scope is a store, so it costs nothing on the
              screens that mount no editor. */}
          <DocumentOutlineScope>
            <SidebarProvider
              defaultOpen={true}
              // The provider's own wrapper asks for `min-h-svh`, which is a floor
              // for a page that grows and a trap for one that does not: anything
              // above it here -- a permission prompt, a banner -- makes the row
              // it sits in shorter than a screen, and the wrapper refuses to
              // follow. Everything below then measures itself against a box
              // taller than the one on screen, and the app scrolls into space
              // that was never there. The shell has a real height; take it.
              className="h-full min-h-0"
              style={
                {
                  "--sidebar-width": "20rem",
                  "--sidebar-width-mobile": "90vw",
                } as React.CSSProperties
              }
            >
              <AppSidebar />
              <div className="flex min-h-0 min-w-0 flex-1 flex-col md:pl-0">
                <div
                  className="sticky top-0 z-50 flex flex-col bg-card/70 backdrop-blur supports-backdrop-filter:bg-card/60 md:border-b"
                  style={{ paddingTop: "var(--safe-area-inset-top)" }}
                >
                  {/* Mobile hamburger lives in BottomNav and search now lives in
                    the sidebar, so this desktop-only row is just recents — and
                    with nothing recent it takes up no room at all. A demo
                    visitor's banner takes the row instead, on every width. */}
                  <DemoBannerOrTabs>
                    {(recentQuery.isLoading || (recentItems?.length ?? 0) > 0) && (
                      <div className="hidden h-12 md:flex">
                        <div className="min-w-0 flex-1">
                          <RecentTabsBar
                            items={recentItems}
                            loading={recentQuery.isLoading}
                            activeKey={activeRecentKey}
                            onClose={handleClearRecent}
                            onCloseOthers={handleCloseOtherRecents}
                            onCloseAll={handleCloseAllRecents}
                          />
                        </div>
                      </div>
                    )}
                  </DemoBannerOrTabs>
                  <OfflineBanner />
                  <CommunityAccessBanner />
                  <PushPermissionPrompt />
                </div>
                <div className="flex min-h-0 flex-1 justify-between">
                  {/*<div
                  className="h-full w-full opacity-20 fixed"
                  style={{
                    backgroundImage: `url(${isDark ? "/images/hexWhite.svg" : "/images/hexBlack.svg"})`,
                    backgroundPosition: "center",
                    backgroundBlendMode: "screen",
                    backgroundSize: "37px 64px",
                  }}
                />*/}
                  {/* The app's scroller. Named twice over: the router restores
                    this element's position across navigations rather than the
                    window's, and pull-to-refresh asks it how far down it is.

                    It spans the row and holds the page's width inside it,
                    rather than being that width itself. A scrollbar renders at
                    the edge of its own scrollport, so a scroller that was also
                    `container mx-auto` put the bar in the middle of the window
                    — floating beside the centred column instead of down the
                    side of the app.

                    `overflow-x-clip` because `overflow-y: auto` alone does not
                    stay on one axis: with the other left `visible`, CSS
                    computes that one to `auto` too, quietly making the shell a
                    horizontal scroller. Anything anywhere that overran then
                    dragged the whole app sideways. Wide content owns its own
                    scroller here — the tool rail and every table already do —
                    so the shell says no to the axis rather than offering a bar
                    nothing should need.

                    `relative`, so this is the containing block for anything on
                    a page that is absolutely positioned with no positioned
                    ancestor of its own -- every `sr-only` label, for one. Those
                    are laid out against the containing block, not the flow, so
                    without this they sat outside the scroller at their in-flow
                    offset from the top of the page, and a long enough page --
                    a comment thread, a delete label on each comment -- put
                    them below the window. The document grew to fit them, and
                    whatever then asked for a scroll (focus moving into the
                    composer, a wheel over anything that was not the scroller)
                    moved the whole app, chrome included, up out of the window.
                    Measured: fifteen comments made the document 3057px tall in
                    a 900px window. Inside `main` they scroll with the comment
                    they label. */}
                  <main
                    data-app-scroll=""
                    data-scroll-restoration-id="app-main"
                    className="relative min-w-0 flex-1 overflow-y-auto overflow-x-clip"
                  >
                    {/* A grid, and `min-h-full` rather than `h-full`, because
                      this sits between the scrollport and the page and must
                      pass a height through without capping one.

                      `h-full` would fix it at the scrollport's height, and a
                      page taller than that would spill past its own bottom
                      padding. `min-h-full` alone grows correctly but leaves
                      `height: auto`, and a percentage height resolves against
                      the parent's *height* — so `h-full` on a page would
                      silently become `auto`. Three pages depend on that chain
                      (My Messages, a document, a plug-in surface): each pins
                      something to an edge and needs a real height to do it.

                      A grid row is definite either way. It is at least the
                      scrollport, grows with a long page, and gives a child's
                      `h-full` an area to resolve against.

                      `grid-cols-[minmax(0,1fr)]` is not decoration. A grid
                      item's automatic minimum is its *content's* minimum, so a
                      page holding anything that will not wrap — a toolbar, a
                      table's widest row — sized the column to that instead of
                      to the container. The container kept its max-width and
                      stayed centred while its content spilled out of the right
                      side of it, which reads as a page that is no longer
                      centred. Flooring the track at 0 hands the item the
                      container's width and lets what is inside scroll or
                      truncate on its own terms. */}
                    {/* A full-bleed route drops the measure and the padding:
                      it lays itself out against the window, and its own header
                      sits against the edges. The height needs no help — the
                      grid row below is already definite, which is what a
                      surface pinning its header and scrolling its middle
                      resolves its `h-full` against. `pb-16` on small screens
                      keeps the bottom bar off the end of it. */}
                    <div
                      className={cn(
                        // The page area: what a page's canvas-sm: and its
                        // siblings measure, sidebar or not.
                        "@container grid min-h-full grid-cols-[minmax(0,1fr)] grid-rows-[1fr]",
                        fullBleed ? "pb-16 md:pb-0" : "container mx-auto p-4 pb-24 md:p-8 md:pb-24"
                      )}
                    >
                      <Suspense fallback={<PageLoader />}>
                        <Outlet />
                      </Suspense>
                    </div>
                  </main>
                </div>
              </div>
              <ProjectActivitySidebar
                projectId={activeProjectId}
                initiativeId={activeProjectInitiativeId}
              />
              <BottomNav />
            </SidebarProvider>
          </DocumentOutlineScope>
        </div>
        <UpdateAnnouncementDialog
          open={updateAvailable.show}
          version={updateAvailable.version}
          onClose={closeDialog}
        />
        {/* Server-side notices queue behind the update prompt: an update is
            about the page the reader is looking at, so it goes first. */}
        <AnnouncementCenter enabled={!updateAvailable.show} />
      </div>
    </CreateActionProvider>
  );
}

/**
 * Signed in with no community: the start flow without the account steps, and
 * the ways to the account's own settings underneath.
 */
function NoCommunityState({
  logout,
  reachesPlatformAreas,
  onBusy,
}: {
  logout: () => void;
  reachesPlatformAreas: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const { t } = useTranslation("communities");
  return (
    <StartFlow
      signedIn
      onBusy={onBusy}
      footer={
        // The ways off this screen that are not joining or making a
        // community: the account's own settings (to delete it, say), the
        // platform's for staff, and signing out.
        <div className="flex flex-wrap justify-center gap-2 border-t pt-4">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/profile">
              <UserCog className="h-4 w-4" />
              {t("noCommunity.accountSettings")}
            </Link>
          </Button>
          {reachesPlatformAreas && (
            <Button variant="ghost" size="sm" asChild>
              <Link to="/settings/operator">
                <Settings className="h-4 w-4" />
                {t("noCommunity.platformSettings")}
              </Link>
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="h-4 w-4" />
            {t("noCommunity.logOut")}
          </Button>
        </div>
      }
    />
  );
}

/**
 * Minimal layout shown when the user has zero community memberships but
 * is on a route that doesn't need community context (``/profile/*``,
 * ``/settings/operator/*``). Renders the matched outlet inside a
 * narrow container with just enough chrome (Back-to-start + logout)
 * to navigate away.
 */
function NoCommunitySettingsShell({ logout }: { logout: () => void }) {
  const { t } = useTranslation("communities");
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div
        className="sticky top-0 z-50 flex flex-col border-b bg-card/70 backdrop-blur supports-backdrop-filter:bg-card/60"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 items-center justify-between px-4">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">{t("noCommunity.shellBackToStart")}</Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="h-4 w-4" />
            {t("noCommunity.logOut")}
          </Button>
        </div>
      </div>
      <main className="container mx-auto min-w-0 p-4 pb-20 md:p-8 md:pb-20">
        <Suspense fallback={<PageLoader />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
