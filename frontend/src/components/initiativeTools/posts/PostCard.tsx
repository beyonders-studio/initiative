import { Link } from "@tanstack/react-router";
import { CalendarClock, Eye, MailOpen, MessageSquare } from "lucide-react";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type PostRead, ReactionTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { BookmarkButton } from "@/components/BookmarkButton";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import { PostBody } from "@/components/initiativeTools/posts/PostBody";
import { PostByline } from "@/components/initiativeTools/posts/PostByline";
import { PostPinButton } from "@/components/initiativeTools/posts/PostPinButton";
import { PostPoll } from "@/components/initiativeTools/posts/PostPoll";
import { PostReadersDialog } from "@/components/initiativeTools/posts/PostReadersDialog";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { TagBadge } from "@/components/tags/TagBadge";
import { useAuth } from "@/hooks/useAuth";
import { useMarkReadOnScreen, usePostReadTracker } from "@/hooks/usePostReadTracker";
import { useMarkPostUnread, useUpdatePost } from "@/hooks/usePosts";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { useCommunityPath } from "@/lib/communityUrl";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { cn } from "@/ui/lib/utils";

interface PostCardProps {
  post: PostRead;
  /** Whether this reader may pin — community admin or an initiative manager. The
   *  server decides again on the request; this only decides what is offered. */
  canPin?: boolean;
  /** Whether this reader moderates the initiative — its community's admins and
   *  the people with Full access there. */
  canModerate?: boolean;
  className?: string;
}

/**
 * One notice on the board.
 *
 * The whole body is rendered, not a preview: a board is for reading, and a
 * notice that needs a click to be read is a notice nobody reads. The headline
 * links to the post's own page, which is where its comments and reactions live.
 *
 * A card only reaches a reader who may see the notice, so a scheduled one is
 * on the board of the people who wrote it and nobody else. It says so, and
 * offers the one thing there is to do about it: put it up now.
 *
 * Being on screen is what marks a notice read — a board is read by scrolling,
 * and asking somebody to click each one would be asking them to do the app's
 * bookkeeping. Marking it unread again puts it back and stops this card
 * counting it while they are still looking at it.
 */
const PostCardInner = ({ post, canPin = false, canModerate = false, className }: PostCardProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const gp = useCommunityPath();
  // Clearing the schedule is what publishes: the same call the author would
  // make by editing, so there is no second route for "now".
  const publishNow = useUpdatePost(post.id, {
    onSuccess: () => toast.success(t("schedule.publishedToast")),
  });

  const { user } = useAuth();
  // A notice you wrote is read by you and has no receipt behind it — the
  // server refuses to record one, because the roster counts who a notice
  // reached and its author is not somebody it had to reach. So there is
  // nothing here to put back to unread.
  const isMine = user?.id === post.created_by;

  const { suppress } = usePostReadTracker();
  const cardRef = useMarkReadOnScreen(post.id, post.is_read);
  const markUnread = useMarkPostUnread({
    onSuccess: () => toast.success(t("read.markedUnread")),
  });
  const [readersOpen, setReadersOpen] = useState(false);
  const unread = useUnreadTree();

  const detailRoute = gp(toolDetailRoute(Tool.post, post.initiative_id, post.id));

  return (
    <Card
      ref={cardRef}
      className={cn(
        // The card is the post's surface — the editor inside it draws no box
        // of its own, so this is what the body sits on.
        "bg-card",
        post.is_pinned && "border-primary/40 bg-primary/[0.03]",
        // A draft reads as provisional rather than as another notice on the
        // board: it is the only card here nobody else can see.
        !post.is_published && "border-dashed",
        // Unread reads as "there is something here", which is a weight the
        // card carries rather than a badge it wears.
        !post.is_read && "border-primary/30 shadow-sm",
        className
      )}
    >
      <CardHeader className="gap-2 pb-3">
        <PinnedBanner post={post} canPin={canPin} />
        {!post.is_published && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
            <span className="inline-flex items-center gap-1.5">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden />
              {post.scheduled_for
                ? t("schedule.scheduledFor", { date: formatDateTime(post.scheduled_for) })
                : t("schedule.notPublished")}
            </span>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              disabled={publishNow.isPending}
              onClick={() => publishNow.mutate({ scheduled_for: null })}
            >
              {t("schedule.publishNow")}
            </Button>
          </div>
        )}
        <PostByline post={post} />
        <div className="flex items-start gap-2">
          {/* The headline takes whatever the controls leave, so the controls
              stay together at the end of the row. Spacing them apart instead
              would put the pin wherever the report button happened to be. */}
          <CardTitle className="min-w-0 flex-1 text-lg leading-tight">
            <Link to={detailRoute} className="hover:underline">
              {post.name}
            </Link>
            {unread.hasResource(post.community_id, Tool.post, post.id) ? (
              <UnreadDot className="ml-2 inline-block align-middle" />
            ) : null}
          </CardTitle>
          <div className="flex shrink-0 items-center gap-1">
            <BookmarkButton
              tool={Tool.post}
              entityId={post.id}
              name={post.name}
              initiativeId={post.initiative_id}
              communityId={post.community_id}
              iconSize="sm"
            />
            {canPin && <PostPinButton post={post} />}
            <ReportButton targetType="post" targetId={post.id} authorId={post.created_by} />
            <ModerationMenu
              targetType="post"
              targetId={post.id}
              canModerate={canModerate}
              reactable
              communityId={post.community_id}
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <PostBody body={post.body} />
        {/* The question, under what was said about it — a poll is the thing a
            notice is asking, and asking before saying reads as a form. */}
        {post.poll && <PostPoll post={post} />}
        {post.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {post.tags.map((tag) => (
              <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {/* Reacting is a read-level gesture — anyone who can see the
              notice can react to it — so the bar is offered to every
              reader, not only to whoever may edit. A notice with reactions
              turned off shows none: there is nothing to join. */}
          {post.reactions_enabled && (
            <ReactionBar
              targetType={ReactionTarget.post}
              targetId={post.id}
              groups={post.reactions}
            />
          )}
          {/* The thread, from the board. A count says there is a conversation
              worth opening; nothing said so far is an invitation rather than a
              "0", which reads as an absence. Both land on the post, because the
              thread lives there. A post with comments turned off says neither —
              there is nothing to join. */}
          {post.comments_enabled && (
            <Link
              to={detailRoute}
              className="inline-flex items-center gap-1.5 text-muted-foreground text-sm hover:text-foreground hover:underline"
            >
              <MessageSquare className="h-4 w-4" aria-hidden />
              {post.comment_count > 0 ? t("comments", { count: post.comment_count }) : t("beFirst")}
            </Link>
          )}
          {/* Whether it landed, which is the point of saying it out loud.
              Offered to every reader, not just the author: they are all on the
              roster it opens, and they all put something on this board. */}
          {post.read_count > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-auto gap-1.5 px-2 py-1 text-muted-foreground text-xs"
              onClick={() => setReadersOpen(true)}
            >
              <Eye className="h-3.5 w-3.5" aria-hidden />
              {t("read.readBy", { count: post.read_count })}
            </Button>
          )}
          {/* Only once it has been read, and never on your own notice — in
              either case the button would be a no-op wearing a label. */}
          {post.is_read && !isMine && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto h-auto gap-1.5 px-2 py-1 text-muted-foreground text-xs"
              disabled={markUnread.isPending}
              onClick={() => {
                // Stop this card counting it again: it is still on screen, and
                // without this the observer would undo the click a beat later.
                suppress(post.id);
                markUnread.mutate(post.id);
              }}
            >
              <MailOpen className="h-3.5 w-3.5" aria-hidden />
              {t("read.markUnread")}
            </Button>
          )}
        </div>
      </CardContent>

      <PostReadersDialog open={readersOpen} onOpenChange={setReadersOpen} postId={post.id} />
    </Card>
  );
};

/**
 * Memoized, and that is load-bearing on a board rather than a micro-optimism.
 *
 * Reading marks notices read as you scroll, and each batch rewrites the cached
 * page — a new array holding the *same* row objects for everything it did not
 * touch. Without this, one row changing re-renders every mounted card, and
 * every card is a Lexical editor. With it, only the row that actually changed
 * re-renders.
 */
export const PostCard = memo(PostCardInner);
