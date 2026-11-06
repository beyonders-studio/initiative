import { HelpCircle, Lock, LockOpen, MessageSquarePlus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CommentCreate,
  type CommentRead,
  ModerationAct,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useCreateComment, useDeleteComment, useUpdateComment } from "@/hooks/useComments";
import { useCommunities } from "@/hooks/useCommunities";
import { useModerate } from "@/hooks/useModeration";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { linkedCommentId } from "@/lib/entityResolver";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { referenceTypeFor } from "@/lib/references";
import { referenceRef } from "@/lib/smartChips";
import { getUserDisplayName } from "@/lib/userDisplay";

import { CommentInput } from "./CommentInput";
import { CommentReferences } from "./CommentReferences";
import { CommentThread } from "./CommentThread";

export interface CommentWithReplies extends CommentRead {
  replies: CommentWithReplies[];
}

/** What a comment thread hangs off: any tool entity, plus tasks (a project's
 *  child, not a tool of its own). */
/** What a comment can hang off: a tool entity, or one of the content-level
 *  extras that carries a thread of its own. Mirrors the backend's
 *  `COMMENT_TARGETS`. */
export type CommentEntity = "task" | "wiki_page" | "collection" | Tool;

interface CommentSectionProps {
  entityType: CommentEntity;
  entityId: number;
  comments?: CommentRead[];
  onCommentCreated?: (comment: CommentRead) => void;
  onCommentDeleted?: (commentId: number) => void;
  onCommentUpdated?: (comment: CommentRead) => void;
  title?: string;
  isLoading?: boolean;
  /** Older conversations the thread has not loaded yet. */
  hasOlder?: boolean;
  isLoadingOlder?: boolean;
  onLoadOlder?: () => void;
  initiativeId: number;
  /** A moderator closed the thread: it reads as before, and nothing is
   *  added to it until a moderator reopens it. */
  locked?: boolean;
  /** Whether this reader moderates the initiative the thread is in. */
  canModerate?: boolean;
}

/** Later first; the id breaks a tie, since it only ever grows. */
const newestFirst = (
  a: Pick<CommentRead, "created_at" | "id">,
  b: Pick<CommentRead, "created_at" | "id">
) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id;

/** One conversation in the thread: a comment and its replies, or replies
 *  whose comment the reader can't see — held, say — under a placeholder. */
type ThreadEntry =
  | { kind: "comment"; comment: CommentWithReplies }
  | { kind: "unavailable"; parentId: number; created_at: string; replies: CommentWithReplies[] };

const entryKey = (entry: ThreadEntry) =>
  entry.kind === "comment" ? `comment-${entry.comment.id}` : `unavailable-${entry.parentId}`;

const entryOrder = (entry: ThreadEntry) =>
  entry.kind === "comment" ? entry.comment : { created_at: entry.created_at, id: -entry.parentId };

/**
 * The thread as it reads: newest conversation at the top, under the box that
 * starts one, and each conversation's replies in the order they were said. A
 * reply is never promoted to a conversation of its own: where the comment it
 * answers isn't there, it sits under an "Unavailable" placeholder instead.
 */
function buildCommentTree(comments: CommentRead[]): ThreadEntry[] {
  const map = new Map<number, CommentWithReplies>();
  const entries: ThreadEntry[] = [];
  const missing = new Map<number, Extract<ThreadEntry, { kind: "unavailable" }>>();

  // First pass: create all nodes
  for (const comment of comments) {
    map.set(comment.id, { ...comment, replies: [] });
  }

  // Second pass: link children to parents
  for (const comment of comments) {
    const node = map.get(comment.id)!;
    const parentId = comment.parent_comment_id;
    if (parentId && map.has(parentId)) {
      map.get(parentId)!.replies.push(node);
    } else if (parentId) {
      const placeholder = missing.get(parentId);
      if (placeholder) {
        placeholder.replies.push(node);
      } else {
        const entry = {
          kind: "unavailable" as const,
          parentId,
          created_at: comment.created_at,
          replies: [node],
        };
        missing.set(parentId, entry);
        entries.push(entry);
      }
    } else {
      entries.push({ kind: "comment", comment: node });
    }
  }

  return entries.sort((a, b) => newestFirst(entryOrder(a), entryOrder(b)));
}

export const CommentSection = ({
  entityType,
  entityId,
  comments = [],
  onCommentCreated,
  onCommentDeleted,
  onCommentUpdated,
  title,
  isLoading = false,
  hasOlder = false,
  isLoadingOlder = false,
  onLoadOlder,
  initiativeId,
  locked = false,
  canModerate = false,
}: CommentSectionProps) => {
  const { t } = useTranslation(["comments", "moderation"]);
  const communityId = useActiveCommunityId() ?? 0;
  // A link to one comment lands on this thread: where it is in an older
  // conversation than the first page holds, the older ones are read until it
  // is here, and the thread scrolls to it.
  const linkedId = typeof window !== "undefined" ? linkedCommentId(window.location.hash) : null;
  const linkedLoaded = linkedId !== null && comments.some((comment) => comment.id === linkedId);
  // How many comments the thread held when it last asked for older ones. A
  // read that brought nothing — it failed, say — stops the search, and the
  // reader's own Load older is left to try again.
  // Kept per search — this thread, in this community, for this comment — so
  // a new one starts afresh.
  const searchKey = `${communityId}:${entityType}:${entityId}:${linkedId}`;
  const askedAt = useRef<{ key: string; count: number } | null>(null);
  useEffect(() => {
    if (linkedId === null || linkedLoaded || !hasOlder || isLoadingOlder) return;
    const asked = askedAt.current?.key === searchKey ? askedAt.current.count : null;
    if (asked !== null && comments.length <= asked) return;
    askedAt.current = { key: searchKey, count: comments.length };
    onLoadOlder?.();
  }, [searchKey, linkedId, linkedLoaded, hasOlder, isLoadingOlder, onLoadOlder, comments.length]);
  const { activeCommunityReadOnly } = useCommunities();
  // A moderator closes or reopens the thread from the thread itself, the
  // same on every kind of thing that takes comments.
  const moderate = useModerate(communityId);
  const toggleLock = () =>
    moderate.mutate(
      {
        target_type: entityType,
        target_id: entityId,
        act: locked ? ModerationAct.unlock_comments : ModerationAct.lock_comments,
      },
      {
        onSuccess: () =>
          toast.success(locked ? t("moderation:menu.unlocked") : t("moderation:menu.locked")),
      }
    );
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const { user } = useAuth();

  // What this thread is a remark about. A comment on a page does not link to
  // the page it is written on, so no composer here offers it — the box at the
  // top, and every reply and edit below.
  const subject = useMemo(
    () => referenceRef(referenceTypeFor(entityType), entityId),
    [entityType, entityId]
  );

  const createComment = useCreateComment({
    onSuccess: (comment) => {
      setContent("");
      setError(null);
      onCommentCreated?.(comment);
    },
    onError: (err) => {
      setError(getErrorMessage(err, "comments:createError"));
    },
  });

  const deleteComment = useDeleteComment({
    onSuccess: (_data, commentId) => {
      setDeleteError(null);
      onCommentDeleted?.(commentId);
    },
    onError: (err) => {
      setDeleteError(getErrorMessage(err, "comments:deleteError"));
    },
  });

  const updateComment = useUpdateComment({
    onSuccess: (comment) => {
      setEditError(null);
      onCommentUpdated?.(comment);
    },
    onError: (err) => {
      setEditError(getErrorMessage(err, "comments:updateError"));
    },
  });

  // Build comment tree
  const commentTree = useMemo(() => buildCommentTree(comments), [comments]);
  const hasComments = comments.length > 0;

  // What was unread when the thread was opened: the comments its
  // notifications named, and everyone else's since a rolled-up line began.
  const unread = useReadOnOpen(entityType, entityId);
  const unreadIds = useMemo(() => {
    const since = unread.since;
    return new Set(
      comments
        .filter(
          (comment) =>
            unread.commentIds.has(comment.id) ||
            (since !== null &&
              comment.created_by !== user?.id &&
              new Date(comment.created_at) > since)
        )
        .map((comment) => comment.id)
    );
  }, [comments, unread, user?.id]);

  // Brought into view once per thread, on the first unread comment.
  const threadRef = useRef<HTMLDivElement>(null);
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    const key = `${entityType}:${entityId}`;
    if (unreadIds.size === 0 || scrolledFor.current === key) return;
    const first = threadRef.current?.querySelector("[data-unread]");
    if (!first) return;
    scrolledFor.current = key;
    first.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [unreadIds, entityType, entityId]);

  // Build display name maps from comment authors
  const userDisplayNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const comment of comments) {
      if (comment.author) {
        const displayName = getUserDisplayName(comment.author);
        map.set(comment.author.id, displayName);
      }
    }
    return map;
  }, [comments]);

  // Each entity kind carries its id under its own `<entity>_id` field, and a
  // comment names exactly one.
  const buildPayload = (commentBody: string, parentCommentId?: number): CommentCreate => {
    const payload: CommentCreate = {
      content: commentBody,
    };
    payload[`${entityType}_id`] = entityId;
    if (parentCommentId) {
      payload.parent_comment_id = parentCommentId;
    }
    return payload;
  };

  const handleSubmit = (commentContent: string) => {
    const normalized = commentContent.trim();
    if (!normalized) {
      setError(t("contentRequired"));
      return;
    }
    createComment.mutate(buildPayload(normalized));
  };

  const handleReply = (parentId: number, replyContent: string) => {
    const normalized = replyContent.trim();
    if (!normalized) return;
    createComment.mutate(buildPayload(normalized, parentId));
  };

  const handleDelete = (commentId: number) => {
    deleteComment.mutate(commentId);
  };

  const handleEdit = async (commentId: number, editedContent: string): Promise<boolean> => {
    const normalized = editedContent.trim();
    if (!normalized) return false;
    try {
      await updateComment.mutateAsync({ commentId, data: { content: normalized } });
      return true;
    } catch {
      return false;
    }
  };

  return (
    // Full width wherever it lands: a comment thread is a conversation, and a
    // narrow column makes every reply wrap. Callers give it its own row rather
    // than a sidebar or a half-width cell.
    <CommentReferences contents={comments.map((comment) => comment.content)}>
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageSquarePlus className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h3>{title ?? t("title")}</h3>
            </div>
            <div className="flex items-center gap-1">
              {canModerate && !activeCommunityReadOnly ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 font-normal text-muted-foreground"
                  disabled={moderate.isPending}
                  onClick={toggleLock}
                >
                  {locked ? (
                    <LockOpen className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Lock className="h-4 w-4" aria-hidden="true" />
                  )}
                  {locked ? t("moderation:menu.unlock") : t("moderation:menu.lock")}
                </Button>
              ) : null}
              <HoverCard>
                <HoverCardTrigger asChild>
                  <button type="button" className="text-muted-foreground hover:text-foreground">
                    <HelpCircle className="h-4 w-4" />
                  </button>
                </HoverCardTrigger>
                <HoverCardContent side="left" align="start" className="w-56">
                  <p className="font-medium text-sm">{t("mentionSyntax")}</p>
                  <ul className="mt-2 space-y-1.5 text-sm">
                    <li>
                      <code className="rounded bg-muted px-1 text-xs">@</code> {t("mentionUser")}
                    </li>
                    <li>
                      <code className="rounded bg-muted px-1 text-xs">#</code>{" "}
                      {t("mentionAnything")}
                    </li>
                    <li className="text-muted-foreground">{t("mentionNarrow")}</li>
                  </ul>
                  <p className="mt-3 font-medium text-sm">{t("formattingSyntax")}</p>
                  <p className="mt-1 text-muted-foreground text-sm">{t("markdownHint")}</p>
                </HoverCardContent>
              </HoverCard>
            </div>
          </CardTitle>
        </CardHeader>

        <CardContent>
          {locked && (
            <p className="mb-3 flex items-center gap-2 text-muted-foreground text-sm">
              <Lock className="h-4 w-4" aria-hidden="true" />
              {t("locked")}
            </p>
          )}
          {activeCommunityReadOnly ? (
            <p className="text-muted-foreground text-sm">{t("readOnlyNote")}</p>
          ) : locked ? null : (
            <CommentInput
              value={content}
              onChange={setContent}
              onSubmit={handleSubmit}
              isSubmitting={createComment.isPending}
              initiativeId={initiativeId}
              subject={subject}
              error={error}
              onClearError={() => setError(null)}
            />
          )}

          {/* One request for everything the whole thread points at: forty
            comments naming the same task ask about it once. */}
          <div ref={threadRef} className="mt-4 space-y-3">
            {isLoading ? (
              <p className="text-muted-foreground text-sm">{t("loading")}</p>
            ) : hasComments ? (
              commentTree.map((entry) => {
                const thread = (comment: CommentWithReplies, depth: number) => (
                  <CommentThread
                    key={comment.id}
                    comment={comment}
                    depth={depth}
                    onReply={handleReply}
                    onDelete={handleDelete}
                    onEdit={handleEdit}
                    currentUserId={user?.id}
                    initiativeId={initiativeId}
                    subject={subject}
                    isSubmitting={
                      createComment.isPending || deleteComment.isPending || updateComment.isPending
                    }
                    canReact={!activeCommunityReadOnly}
                    canReply={!activeCommunityReadOnly && !locked}
                    canEdit={!locked}
                    canModerate={canModerate}
                    deleteError={deleteComment.variables === comment.id ? deleteError : null}
                    userDisplayNames={userDisplayNames}
                    unreadIds={unreadIds}
                  />
                );
                if (entry.kind === "comment") return thread(entry.comment, 0);
                return (
                  <div key={entryKey(entry)}>
                    <p className="rounded-md border border-dashed px-3 py-2 text-muted-foreground text-sm italic">
                      {t("unavailable")}
                    </p>
                    <div className="mt-3 space-y-3">
                      {entry.replies.map((reply) => thread(reply, 1))}
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-muted-foreground text-sm">{t("empty")}</p>
            )}
            {hasOlder && onLoadOlder ? (
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                onClick={onLoadOlder}
                disabled={isLoadingOlder}
              >
                {isLoadingOlder ? t("loading") : t("loadOlder")}
              </Button>
            ) : null}
            {deleteError && !deleteComment.variables && (
              <p className="text-destructive text-sm">{deleteError}</p>
            )}
            {editError && <p className="text-destructive text-sm">{editError}</p>}
          </div>
        </CardContent>
      </Card>
    </CommentReferences>
  );
};
