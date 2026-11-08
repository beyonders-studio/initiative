/**
 * One comment thread, ready to drop at the bottom of the page it belongs on.
 *
 * It takes the ENTITY, not a pile of fields pulled out of it: every tool's read
 * schema carries the same three facts a thread needs — its id, the initiative
 * it lives in, and whether its comments are switched on (`comments_enabled`,
 * which `tools_test.py` holds every tool to). Deriving them here means a tool
 * page says which tool and which row, and a seventh tool needs no new wiring at
 * all.
 *
 * `target` splits the thread from what answers for it, which is what the
 * backend does too: a wiki page's conversation is the page's, while the
 * switch, the sharing and the initiative are the wiki's. Left out, the thread
 * is the tool entity's own.
 */

import { useMemo } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { CommentEntity } from "@/components/comments/CommentSection";
import { CommentSection } from "@/components/comments/CommentSection";
import {
  type CommentThreadParams,
  useComments,
  useCommentsCache,
  useCommentThreadState,
} from "@/hooks/useComments";
import type { ToolCommentEntity } from "@/lib/tools";
import { StatusMessage } from "@/ui/status-message";

interface ToolCommentsPanelProps {
  /** Which tool answers for the thread — its switch, its sharing. */
  tool: Tool;
  /** The tool entity itself, as its read schema returns it. */
  entity: ToolCommentEntity;
  /** The thread itself, where it is not the tool entity's own — a wiki page.
   *  Its `type` is the comment target's field name. */
  target?: { type: CommentEntity; id: number };
  title?: string;
  /** Called with +1/-1 when the thread grows or shrinks, for a page that shows
   *  a comment count of its own. */
  onCountChange?: (delta: number) => void;
}

export const ToolCommentsPanel = ({
  tool,
  entity,
  target,
  title,
  onCountChange,
}: ToolCommentsPanelProps) => {
  const targetType: CommentEntity = target?.type ?? tool;
  const entityId = target?.id ?? entity.id;
  const enabled = entity.comments_enabled ?? true;
  // A community-level entity (an plugin-installed calendar) belongs to no initiative;
  // 0 is what the mention lookups read as "no initiative to search".
  const initiativeId = entity.initiative_id ?? 0;

  const params = useMemo<CommentThreadParams>(() => {
    const next: CommentThreadParams = {};
    next[`${targetType}_id`] = entityId;
    return next;
  }, [targetType, entityId]);

  const commentsQuery = useComments(params, { enabled: Number.isFinite(entityId) && enabled });
  const thread = useCommentThreadState(params, {
    enabled: Number.isFinite(entityId) && enabled,
  });
  // Write the new row straight into this thread's cache, so the comment
  // appears under the box the moment it posts.
  const cache = useCommentsCache(params);

  if (!enabled) return null;

  return (
    <div className="space-y-2">
      {commentsQuery.isError && <StatusMessage onRetry={commentsQuery.refetch} />}
      <CommentSection
        entityType={targetType}
        entityId={entityId}
        comments={commentsQuery.data ?? []}
        isLoading={commentsQuery.isLoading}
        hasOlder={commentsQuery.hasNextPage}
        isLoadingOlder={commentsQuery.isFetchingNextPage}
        onLoadOlder={() => void commentsQuery.fetchNextPage()}
        initiativeId={initiativeId}
        locked={thread.data?.locked ?? false}
        canModerate={thread.data?.canModerate ?? false}
        onCommentCreated={(comment) => {
          cache.putComment(comment);
          onCountChange?.(1);
        }}
        onCommentDeleted={(commentId) => {
          cache.removeComment(commentId);
          onCountChange?.(-1);
        }}
        onCommentUpdated={cache.putComment}
        {...(title !== undefined ? { title } : {})}
      />
    </div>
  );
};
