/**
 * The community home's Comments circle: the latest comments anywhere in the
 * community, a card each, with what was said and how it landed.
 *
 * It fills the tray under the front page's rail.
 * The endpoint only returns comments on entities the user may see, so no
 * filtering happens here.
 */

import { Link } from "@tanstack/react-router";
import { MessageSquare } from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ReactionTarget, type RecentActivityEntry } from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { CommentReferences } from "@/components/comments/CommentReferences";
import { FeedCardSkeleton } from "@/components/communityHome/CommunityActivityFeed";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useRecentComments } from "@/hooks/useComments";
import { useCommunityPath } from "@/lib/communityUrl";
import { entityRefRoute, TOOLS, taskRoute, toolDetailRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Card } from "@/ui/card";
import { cn } from "@/ui/lib/utils";
import { RelativeTime } from "@/ui/relative-time";

const RECENT_COMMENTS_PARAMS = { limit: 10 };

/**
 * Reports whether an element's content overflows the lines it is clamped to.
 *
 * Only measured while collapsed — expanding removes the clamp, which would
 * otherwise read back as "not truncated" and retract the control that just
 * expanded it.
 */
const useIsTruncated = (ref: React.RefObject<HTMLElement | null>, collapsed: boolean) => {
  const [isTruncated, setIsTruncated] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !collapsed) return;

    const measure = () => setIsTruncated(element.scrollHeight > element.clientHeight + 1);
    measure();

    // The clamp follows the column's width, so a resize can change the answer.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, collapsed]);

  return isTruncated;
};

const CommentEntry = ({ entry }: { entry: RecentActivityEntry }) => {
  const { t } = useTranslation(["communityHome", "comments"]);
  const gp = useCommunityPath();
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const isTruncated = useIsTruncated(contentRef, !expanded);

  // A null initiative names a community-level address, which the route builders
  // handle.
  const initiativeId = entry.initiative_id ?? null;
  const tool = TOOLS.find((candidate) => candidate === entry.entity_type) ?? null;
  const taskId = entry.entity_type === "task" ? entry.entity_id : null;

  let linkTo: string | undefined;
  if (taskId) {
    linkTo = gp(
      entry.project_id != null
        ? taskRoute(initiativeId, entry.project_id, taskId)
        : entityRefRoute("task", taskId)
    );
  } else if (tool && entry.entity_id) {
    linkTo = gp(toolDetailRoute(tool, initiativeId, entry.entity_id));
  }

  const contextParts: string[] = [];
  if (entry.entity_name) {
    contextParts.push(t("recentComments.onEntity", { entityName: entry.entity_name }));
  }
  // A task comment also names the project its task is in.
  if (entry.project_name) {
    contextParts.push(t("recentComments.inProject", { projectName: entry.project_name }));
  }

  const body = (
    <>
      <div className="flex items-center gap-3">
        {entry.author ? (
          <ProfileAvatar
            user={entry.author}
            decorations={entry.author.profile_decorations}
            presence={entry.author.presence}
            className="size-9 shrink-0"
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate font-medium text-sm">
              {getUserDisplayName(entry.author, t("recentComments.unknownAuthor"))}
            </span>
            <RelativeTime
              date={entry.created_at}
              className="shrink-0 text-muted-foreground text-xs"
            />
          </div>
          {contextParts.length > 0 && (
            <p className="truncate text-muted-foreground text-xs">{contextParts.join(" ")}</p>
          )}
        </div>
      </div>
      <CommentContent
        ref={contentRef}
        content={entry.content}
        // The card is itself a link, so the body must not hold one.
        disableLinks
        className={cn("mt-3", !expanded && "line-clamp-4")}
      />
    </>
  );

  return (
    <li>
      <Card className={cn("p-4 transition-colors", linkTo && "hover:bg-accent/40")}>
        {linkTo ? (
          <Link to={linkTo} className="block">
            {body}
          </Link>
        ) : (
          body
        )}
        {/* Outside the link above: a button nested in one is neither valid nor
            clickable without fighting the navigation. */}
        {(isTruncated || expanded) && (
          <button
            type="button"
            className="mt-1 font-medium text-primary text-xs hover:underline"
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? t("recentComments.showLess") : t("recentComments.readMore")}
          </button>
        )}
        {/* Read-only here, and also outside the link: the feed shows how a
            comment landed, and reacting to one belongs in the thread it is in —
            which is exactly where the card already goes. */}
        {entry.reactions?.length ? (
          <ReactionBar
            className="mt-3"
            targetType={ReactionTarget.comment}
            targetId={entry.comment_id}
            groups={entry.reactions}
            canReact={false}
          />
        ) : null}
      </Card>
    </li>
  );
};

export const CommunityRecentComments = () => {
  const { t } = useTranslation(["communityHome", "comments"]);
  const { data: comments, isLoading, isError } = useRecentComments(RECENT_COMMENTS_PARAMS);
  const contents = useMemo(() => (comments ?? []).map((entry) => entry.content), [comments]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
          <FeedCardSkeleton key={i} />
        ))}
      </div>
    );
  }
  if (isError) {
    return <p className="p-2 text-destructive text-sm">{t("recentComments.loadError")}</p>;
  }
  if (!comments || comments.length === 0) {
    return (
      <div className="flex h-50 flex-col items-center justify-center gap-2 text-muted-foreground text-sm">
        <MessageSquare className="h-8 w-8 opacity-50" aria-hidden="true" />
        <span>{t("recentComments.noComments")}</span>
      </div>
    );
  }
  return (
    // What the comments mention is read for the whole strip at once.
    <CommentReferences contents={contents}>
      <ul className="space-y-3">
        {comments.map((entry) => (
          <CommentEntry key={entry.comment_id} entry={entry} />
        ))}
      </ul>
    </CommentReferences>
  );
};
