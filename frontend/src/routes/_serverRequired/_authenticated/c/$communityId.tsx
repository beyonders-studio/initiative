import { createFileRoute, Outlet, redirect, useLocation, useParams } from "@tanstack/react-router";
import { Lock, ShieldAlert } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import {
  CommunityStatusNotice,
  communityStatusNoticeApplies,
} from "@/components/communities/CommunityStatusNotice";
import { StatusMessage } from "@/components/StatusMessage";
import { CommunityHomeSkeleton, PageSkeleton } from "@/components/skeletons/PageSkeletons";
import { HelpLink } from "@/components/support/HelpLink";
import { useCommunities } from "@/hooks/useCommunities";
import { useToolPageTitle } from "@/hooks/useToolPageTitle";
import { prefetchViewPreferences } from "@/lib/viewPreferences";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId")({
  beforeLoad: async ({ context, params, cause }) => {
    const communityId = Number(params.communityId);
    const { communities } = context;

    // Validate communityId is a valid number
    if (!Number.isFinite(communityId) || communityId <= 0) {
      throw redirect({ to: "/" });
    }

    // Skip membership validation while communities are still loading
    // The component will handle validation once data is available
    // Don't set the community ID yet — it may be invalid and would poison
    // the SPA's community state if the user isn't a member.
    if (communities?.loading) {
      return { urlCommunityId: communityId, urlCommunity: null };
    }

    // Validate membership
    const communityList = communities?.communities ?? [];
    const community = communityList.find((g) => g.id === communityId);
    if (!community) {
      // Let the component render a "not a member" message
      return { urlCommunityId: communityId, urlCommunity: null };
    }

    // A closed community is never adopted as this tab's community: nothing inside
    // it answers, so nothing should be asked of it. The component says so.
    if (!community.can.enter) {
      return { urlCommunityId: communityId, urlCommunity: null };
    }

    // beforeLoad ALSO runs for link PRELOADS (defaultPreload: "intent" —
    // hovering any cross-community link, e.g. a recents tab). A preload must be
    // side-effect free: resetting caches on hover would ping-pong the app
    // between communities. Only a real navigation adopts the community.
    if (cause === "preload") {
      return { urlCommunityId: communityId, urlCommunity: community };
    }

    // Adopt this tab's community from the URL into local state (rail highlight,
    // query keys) before child routes render. Per-tab and local only — the
    // community itself travels in each request's /c/{communityId} path.
    await communities?.syncCommunityFromUrl(communityId);
    // The person's views of the community's lists, which most of its pages
    // open with.
    prefetchViewPreferences(communityId);

    // Provide validated community info to child routes via route context
    return { urlCommunityId: communityId, urlCommunity: community };
  },
  component: CommunityLayout,
});

/** The community subtree's waiting state — shown while the community list is still
 *  arriving, and while this tab is catching up to the URL's community. The front
 *  page gets its own outline; anything deeper gets a page's. */
/** Names the browser tab after the tool the route is in. A component of its
 *  own so it asks only once this tab has adopted the URL's community. */
function ToolPageTitle() {
  useToolPageTitle();
  return null;
}

function CommunityLoading({ communityId }: { communityId: number }) {
  const pathname = useLocation({ select: (location) => location.pathname });
  const atHome = pathname === `/c/${communityId}` || pathname === `/c/${communityId}/`;
  return atHome ? <CommunityHomeSkeleton /> : <PageSkeleton />;
}

function CommunityLayout() {
  const { t } = useTranslation("communities");
  const params = useParams({ from: "/_serverRequired/_authenticated/c/$communityId" });
  const communityId = Number(params.communityId);
  const { communities, activeCommunityId, loading, syncCommunityFromUrl } = useCommunities();

  // Verify membership — must happen before syncing community context
  const community = !loading ? communities.find((g) => g.id === communityId) : undefined;
  const isMember = Boolean(community);
  const closed = community !== undefined && !community.can.enter;

  // Sync community context only after membership is confirmed.
  // This prevents setting an invalid community ID on the API client,
  // which would cause "unable to load" errors on the redirect target.
  useEffect(() => {
    if (isMember && !closed && Number.isFinite(communityId)) {
      void syncCommunityFromUrl(communityId);
    }
  }, [communityId, isMember, closed, syncCommunityFromUrl]);

  if (loading) {
    return <CommunityLoading communityId={communityId} />;
  }

  if (!community) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("notMember.title")}
          description={t("notMember.description")}
          backTo="/"
          backLabel={t("notMember.backToHome")}
        />
      </div>
    );
  }

  // A suspended community is in time out: nobody in it reaches anything,
  // settings included, until the platform lifts it. Its administrators still
  // see it listed, and land here rather than on a page of refusals.
  if (closed) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <StatusMessage
          icon={<Lock />}
          title={t("closed.title")}
          description={`${t("closed.description")} ${
            community.contact_email
              ? t("closed.contact", { email: community.contact_email })
              : t("closed.contactNobody")
          }`}
          action={
            <HelpLink topic={SupportTopic.community} communityId={community.id} variant="outline" />
          }
          backTo="/"
          backLabel={t("notMember.backToHome")}
        />
      </div>
    );
  }

  // Everything below reads this tab's active community for its query keys, and that
  // value adopts the URL in the effect above — which runs a render AFTER the
  // community list arrives, so `beforeLoad` had nothing to adopt on a cold load.
  // Holding the subtree until the two agree is what keeps a fresh tab opened
  // straight onto another community's URL from issuing a page of community-scoped
  // requests against the community this tab started on and then repeating them.
  if (activeCommunityId !== communityId) {
    return <CommunityLoading communityId={communityId} />;
  }

  const notice = communityStatusNoticeApplies(community) ? (
    <CommunityStatusNotice key={`${community.id}:${community.status}`} community={community} />
  ) : null;

  return (
    <>
      <ToolPageTitle />
      {notice}
      <Outlet />
    </>
  );
}
