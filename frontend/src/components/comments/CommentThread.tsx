import { Pencil, Reply, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ReactionTarget } from "@/api/generated/initiativeAPI.schemas";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { linkedCommentId } from "@/lib/entityResolver";
import { getUserDisplayName, isAnonymizedUser } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { useRelativeTime } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";

import { CommentContent } from "./CommentContent";
import { CommentInput } from "./CommentInput";
import type { CommentWithReplies } from "./CommentSection";

/**
 * Nesting is indented for three levels and then stops — past that the
 * conversation is better read as a flat run than as a staircase off the right
 * edge, especially on a phone.
 */
const MAX_VISUAL_DEPTH = 3;

/**
 * The thread line takes a different theme colour at each level, cycling
 * through the chart palette. Depth is the one thing a nested thread has to
 * convey and indentation alone stops conveying it once it is capped, so the
 * colour carries it the rest of the way — and it reads as the app's own
 * palette rather than as decoration bolted on.
 */
const THREAD_LINE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const threadLineColor = (depth: number) =>
  THREAD_LINE_COLORS[(depth - 1) % THREAD_LINE_COLORS.length];

interface CommentThreadProps {
  comment: CommentWithReplies;
  depth: number;
  onReply: (parentId: number, content: string) => void;
  onDelete: (commentId: number) => void;
  onEdit: (commentId: number, content: string) => Promise<boolean>;
  currentUserId?: number;
  initiativeId: number;
  /** The thing the thread is on, as a reference (`file:12`). Never offered
   *  by a reply or an edit — see `CommentInput.subject`. */
  subject?: string | null;
  isSubmitting?: boolean;
  /** False while the viewer may read the thread but not write to it. */
  canReact?: boolean;
  /** False while the thread takes no replies: it is locked, or the community
   *  is read-only. */
  canReply?: boolean;
  /** False while a moderator has the thread locked: what is in it stands as
   *  it was, and its authors may only take their own words back. */
  canEdit?: boolean;
  /** Whether the viewer moderates the initiative the thread is in. */
  canModerate?: boolean;
  deleteError?: string | null;
  userDisplayNames?: Map<number, string>;
  /** Comments that were unread when the thread was opened. */
  unreadIds?: Set<number>;
  taskTitles?: Map<number, string>;
  docTitles?: Map<number, string>;
  projectNames?: Map<number, string>;
}

export const CommentThread = ({
  comment,
  depth,
  onReply,
  onDelete,
  onEdit,
  currentUserId,
  initiativeId,
  subject,
  isSubmitting = false,
  canReact = true,
  canReply = true,
  canEdit: editable = true,
  canModerate = false,
  deleteError,
  userDisplayNames = new Map(),
  unreadIds,
  taskTitles = new Map(),
  docTitles = new Map(),
  projectNames = new Map(),
}: CommentThreadProps) => {
  const { t } = useTranslation(["comments", "common", "moderation"]);
  const relativeCreatedAt = useRelativeTime(comment.created_at);
  const [isReplying, setIsReplying] = useState(false);
  const [replyContent, setReplyContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(comment.content);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // An import that could not match this comment's author to an account
  // carries the source's own name for them. It is a name and not an account:
  // no picture, no profile, no presence, because there is nobody here to
  // show. It wins over the row's `created_by`, which names the import that
  // wrote the row rather than whoever said this.
  const importedAuthorName = comment.imported_author_name?.trim() || null;
  const anonymizedAuthor = !importedAuthorName && isAnonymizedUser(comment.author);
  // A comment a plug-in wrote as its community names no account, and neither
  // does a note the platform wrote on an operations case; the platform's
  // notes say what wrote them.
  const displayName =
    importedAuthorName ??
    (comment.created_by == null
      ? comment.system_kind
        ? t("comments:platformAuthor")
        : t("comments:pluginAuthor")
      : getUserDisplayName(comment.author ?? { id: comment.created_by }));
  // The server says who may delete, from the rule the delete route applies.
  const canDelete = comment.can_remove;
  const canEdit = editable && currentUserId === comment.created_by;
  const visualDepth = Math.min(depth, MAX_VISUAL_DEPTH);
  const isEdited = Boolean(comment.updated_at);
  const isUnread = unreadIds?.has(comment.id) ?? false;
  // A link to this comment (`/go/comment/{id}`) lands here: it is scrolled to
  // and marked out from the rest of the thread.
  const isLinked =
    typeof window !== "undefined" && linkedCommentId(window.location.hash) === comment.id;
  const anchor = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (isLinked) anchor.current?.scrollIntoView?.({ block: "center" });
  }, [isLinked]);

  // A tombstone: a comment a moderator took down, or one its author deleted
  // with replies under it. It keeps its place for them and says nothing else.
  const removal = comment.removed ?? null;
  const tombstoneText = !removal
    ? null
    : removal.by === "author"
      ? t("removed.byAuthor")
      : removal.reason === "illegal"
        ? t("removed.legal")
        : t("removed.byModerator", {
            reason: t(`moderation:removalReasons.${removal.reason ?? "other"}`),
          });
  // A comment still in its author's trash takes no replies; a moderator's
  // tombstone does, since the conversation around it goes on.
  const replyable = canReply && (!removal || removal.by === "moderator");
  // A form opened before the thread was locked goes with the lock; what was
  // typed in it stays, for when the thread is reopened.
  const editing = isEditing && canEdit;
  const replying = isReplying && replyable;

  const handleReplySubmit = (content: string) => {
    onReply(comment.id, content);
    setReplyContent("");
    setIsReplying(false);
  };

  const handleEditSubmit = async (content: string) => {
    const success = await onEdit(comment.id, content);
    if (success) {
      setIsEditing(false);
    }
  };

  const handleEditCancel = () => {
    setIsEditing(false);
    setEditContent(comment.content);
  };

  return (
    <div
      id={`comment-${comment.id}`}
      ref={anchor}
      className={visualDepth > 0 ? "ml-4 border-l-2 pl-4" : ""}
      style={visualDepth > 0 ? { borderColor: threadLineColor(visualDepth) } : undefined}
    >
      {tombstoneText !== null ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed px-3 py-2">
          <p className="text-muted-foreground text-sm italic">{tombstoneText}</p>
          {replyable && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => setIsReplying(!isReplying)}
            >
              <Reply className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="sr-only sm:not-sr-only">{t("reply")}</span>
            </Button>
          )}
        </div>
      ) : (
        <div
          // What a report of the comment pictures.
          data-report-target
          data-unread={isUnread || undefined}
          data-linked={isLinked || undefined}
          className={cn(
            "rounded-md border border-border p-3",
            isUnread && "border-primary/50 bg-primary/5",
            isLinked && "ring-2 ring-primary ring-offset-2 ring-offset-background"
          )}
        >
          <div className="flex gap-3">
            {/* The same picture component the profile and the sidebar draw, so
              a frame someone put on shows wherever they appear at a size it
              reads at — and the presence dot with it. An anonymized author has
              neither a picture nor a profile to have decorated. */}
            <ProfileAvatar
              user={
                anonymizedAuthor || importedAuthorName
                  ? { id: null }
                  : (comment.author ?? { id: comment.created_by })
              }
              decorations={
                anonymizedAuthor || importedAuthorName ? null : comment.author?.profile_decorations
              }
              presence={
                anonymizedAuthor || importedAuthorName ? undefined : comment.author?.presence
              }
              className="size-9"
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
                {/* The name is the way to the person, the same as a mention of
                  them is. An imported author and an erased account are names
                  with nobody behind them, so they stay words. */}
                <UserHoverLink
                  user={anonymizedAuthor || importedAuthorName ? null : comment.author}
                  className="font-medium text-foreground"
                >
                  {displayName}
                </UserHoverLink>
                {importedAuthorName && (
                  <span className="whitespace-nowrap">{t("importedAuthor")}</span>
                )}
                <span className="whitespace-nowrap">
                  {relativeCreatedAt}
                  {isEdited && <span className="ml-1 text-muted-foreground">{t("edited")}</span>}
                </span>
                {isUnread && <UnreadDot />}
                {!editing && (
                  <div className="ml-auto flex items-center gap-1">
                    {replyable && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => setIsReplying(!isReplying)}
                      >
                        <Reply className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="sr-only sm:not-sr-only">{t("reply")}</span>
                      </Button>
                    )}
                    {canEdit && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => setIsEditing(true)}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="sr-only sm:not-sr-only">{t("common:edit")}</span>
                      </Button>
                    )}
                    {canDelete && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-destructive text-xs hover:text-destructive"
                        disabled={isSubmitting}
                        onClick={() => setConfirmingDelete(true)}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        <span className="sr-only">{t("deleteComment")}</span>
                      </Button>
                    )}
                    <ReportButton
                      targetType="comment"
                      targetId={comment.id}
                      authorId={comment.created_by}
                      size="sm"
                      className="h-7 px-2 text-xs"
                    />
                    <ModerationMenu
                      targetType="comment"
                      targetId={comment.id}
                      canModerate={canModerate}
                      reactable
                      className="h-7 w-7"
                    />
                  </div>
                )}
              </div>
              <div className="mt-2 text-foreground text-sm">
                {editing ? (
                  <CommentInput
                    value={editContent}
                    onChange={setEditContent}
                    onSubmit={handleEditSubmit}
                    placeholder={t("editPlaceholder")}
                    submitLabel={t("common:save")}
                    isSubmitting={isSubmitting}
                    initiativeId={initiativeId}
                    subject={subject}
                    onCancel={handleEditCancel}
                    autoFocus
                    compact
                  />
                ) : (
                  <CommentContent content={comment.content} />
                )}
              </div>
              {!editing && (
                <ReactionBar
                  className="mt-2"
                  targetType={ReactionTarget.comment}
                  targetId={comment.id}
                  groups={comment.reactions}
                  canReact={canReact}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Reply input */}
      {replying && (
        <div className="mt-2 ml-4">
          <CommentInput
            value={replyContent}
            onChange={setReplyContent}
            onSubmit={handleReplySubmit}
            placeholder={t("replyPlaceholder")}
            submitLabel={t("reply")}
            isSubmitting={isSubmitting}
            initiativeId={initiativeId}
            subject={subject}
            onCancel={() => {
              setIsReplying(false);
              setReplyContent("");
            }}
            autoFocus
            compact
          />
        </div>
      )}

      {/* Delete error */}
      {deleteError && <p className="mt-1 text-destructive text-sm">{deleteError}</p>}

      {canDelete && (
        <ConfirmDialog
          open={confirmingDelete}
          onOpenChange={setConfirmingDelete}
          title={t("deleteConfirmTitle")}
          description={
            comment.replies.length > 0
              ? t("deleteConfirmWithReplies")
              : t("deleteConfirmDescription")
          }
          confirmLabel={t("deleteComment")}
          destructive
          onConfirm={() => {
            setConfirmingDelete(false);
            onDelete(comment.id);
          }}
        />
      )}

      {/* Nested replies */}
      {comment.replies.length > 0 && (
        <div className="mt-3 space-y-3">
          {comment.replies.map((reply) => (
            <CommentThread
              key={reply.id}
              comment={reply}
              depth={depth + 1}
              onReply={onReply}
              onDelete={onDelete}
              onEdit={onEdit}
              currentUserId={currentUserId}
              initiativeId={initiativeId}
              subject={subject}
              isSubmitting={isSubmitting}
              canReact={canReact}
              canReply={canReply}
              canEdit={editable}
              canModerate={canModerate}
              deleteError={deleteError}
              userDisplayNames={userDisplayNames}
              unreadIds={unreadIds}
              taskTitles={taskTitles}
              docTitles={docTitles}
              projectNames={projectNames}
            />
          ))}
        </div>
      )}
    </div>
  );
};
