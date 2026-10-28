import { useBlocker } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { CalendarClock, Loader2, Vote } from "lucide-react";
import {
  createContext,
  lazy,
  type ReactNode,
  Suspense,
  useContext,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type PostRead,
  type PostUpdate,
  ReactionTarget,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import {
  emptyPollDraft,
  isPollDraftValid,
  type PollDraft,
  PollEditor,
  pollDraftFromRead,
  pollDraftToWrite,
} from "@/components/initiativeTools/posts/PollEditor";
import { PostByline } from "@/components/initiativeTools/posts/PostByline";
import { PostPoll } from "@/components/initiativeTools/posts/PostPoll";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { TagBadge } from "@/components/tags/TagBadge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { POST_SAVES, useDeletePostPoll, useSetPostPoll, useUpdatePost } from "@/hooks/usePosts";
import { useCommunityPath } from "@/lib/communityUrl";
import { normalizeEditorState } from "@/lib/editorState";
import { formatDateTime, fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { MAX_POST_TEXT_CHARS } from "@/lib/posts";
import { referenceRef } from "@/lib/smartChips";
import { cn } from "@/lib/utils";

import { type DetailKind, useItemContext } from "./DetailLayoutView";
import { filledBy } from "./detailLayout";
import { POST_LAYOUT, postFields } from "./posts";

const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);

/** What a notice's detail shares with its parts, beside the notice itself. */
export interface PostLayoutContext {
  /** The server says the reader may change the notice. */
  canEdit: boolean;
  /** The reader manages its initiative, which pins and unpins. */
  canPin: boolean;
  /** Drawn in the layout editor, where nothing is changed. */
  preview?: boolean;
}

const usePostLayout = useItemContext<PostLayoutContext>;

/** The notice's unsaved body and poll, kept above the layout so a part the
 *  layout moves keeps its draft. */
interface PostDrafts {
  body: SerializedEditorState | null;
  setBody: (body: SerializedEditorState | null) => void;
  poll: PollDraft | null;
  setPoll: (poll: PollDraft | null) => void;
}

const Drafts = createContext<PostDrafts | null>(null);

const useDrafts = (): PostDrafts => {
  const drafts = useContext(Drafts);
  if (!drafts) throw new Error("A notice's detail part is drawn outside its detail");
  return drafts;
};

/** Leaving with unsaved words is asked about first, for a reload too. */
const useUnsavedGuard = (dirty: boolean) => {
  const { t } = useTranslation("posts");
  const blocker = useBlocker({
    shouldBlockFn: () => dirty,
    enableBeforeUnload: () => dirty,
    withResolver: true,
  });
  return (
    <ConfirmDialog
      open={blocker.status === "blocked"}
      onOpenChange={(open) => {
        if (!open) blocker.reset?.();
      }}
      title={t("unsaved.title")}
      description={t("unsaved.body")}
      confirmLabel={t("unsaved.leave")}
      cancelLabel={t("unsaved.stay")}
      onConfirm={() => blocker.proceed?.()}
      destructive
    />
  );
};

/** Who wrote it and whether it is pinned. */
const Byline = ({ post }: { post: PostRead }) => {
  const { canPin } = usePostLayout();
  return (
    <div className="space-y-2">
      <PostByline post={post} inline />
      <PinnedBanner post={post} canPin={canPin} />
    </div>
  );
};

/** When a notice not yet up goes up: moved, or put up now, by whoever may
 *  edit it. Nothing for one already up. */
const Schedule = ({ post }: { post: PostRead }) => {
  const { t } = useTranslation("posts");
  const { canEdit, preview } = usePostLayout();
  const reschedule = useUpdatePost(post.id, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });
  if (post.is_published) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-dashed p-3">
      {canEdit && !preview ? (
        <>
          <Label
            htmlFor="post-schedule"
            className="inline-flex items-center gap-1.5 text-muted-foreground text-sm"
          >
            <CalendarClock className="h-4 w-4" aria-hidden />
            {t("schedule.publishesAt")}
          </Label>
          <DateTimePicker
            id="post-schedule"
            includeTime
            value={toLocalDateTimeInput(post.scheduled_for)}
            placeholder={t("schedule.placeholder")}
            // Only a real instant moves it: publishing cannot be undone, and
            // emptying the box to retype it must not put the notice up.
            onChange={(value) => {
              const when = fromLocalDateTimeInput(value);
              if (when) reschedule.mutate({ scheduled_for: when });
            }}
          />
          <Button
            size="sm"
            className="ml-auto"
            disabled={reschedule.isPending}
            onClick={() => reschedule.mutate({ scheduled_for: null })}
          >
            {t("schedule.publishNow")}
          </Button>
        </>
      ) : (
        <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
          <CalendarClock className="h-4 w-4" aria-hidden />
          {post.scheduled_for
            ? t("schedule.scheduledFor", { date: formatDateTime(post.scheduled_for) })
            : t("schedule.notPublished")}
        </p>
      )}
    </div>
  );
};

/** What it says, in the editor the board renders it with, saved by Save: a
 *  notice is not a shared document, and a half-written correction is not
 *  broadcast as it is typed. */
const Body = ({ post }: { post: PostRead }) => {
  const { t } = useTranslation(["posts", "common"]);
  const { canEdit, preview } = usePostLayout();
  const writable = canEdit && !preview;
  const { body: draft, setBody: setDraft } = useDrafts();
  const update = useUpdatePost(post.id, {
    onSuccess: () => {
      setDraft(null);
      toast.success(t("detailsUpdated"));
    },
  });
  return (
    <div className="min-w-0 space-y-3">
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <Editor
          key={post.id}
          editorSerializedState={draft ?? normalizeEditorState(post.body)}
          onSerializedChange={setDraft}
          readOnly={!writable}
          showToolbar={writable}
          initiativeId={post.initiative_id}
          subject={referenceRef(SearchEntityType.post, post.id)}
          supportsEntityMentions
          variant="post"
          maxLength={MAX_POST_TEXT_CHARS}
          // Reading, the padding comes from this box; writing, the editor
          // reserves room for its toolbar.
          className={cn("rounded-lg border bg-card", !writable && "py-2")}
        />
      </Suspense>
      {writable && draft !== null && (
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={update.isPending}
            onClick={() => update.mutate({ body: { ...draft } })}
          >
            {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {update.isPending ? t("saving") : t("common:save")}
          </Button>
        </div>
      )}
    </div>
  );
};

/** Reacting is a reader's gesture: offered to everyone who can see it, where
 *  reactions are on. */
const Reactions = ({ post }: { post: PostRead }) =>
  post.reactions_enabled ? (
    <ReactionBar targetType={ReactionTarget.post} targetId={post.id} groups={post.reactions} />
  ) : null;

/** The question it asks, answered by every reader and rewritten, with its
 *  own Save, by whoever may edit it. Once answered, its choices stay. */
const Poll = ({ post }: { post: PostRead }) => {
  const { t } = useTranslation(["posts", "common"]);
  const { canEdit, preview } = usePostLayout();
  const { poll: pollDraft, setPoll: setPollDraft } = useDrafts();
  const savePoll = useSetPostPoll(post.id, {
    onSuccess: () => {
      setPollDraft(null);
      toast.success(t("poll.saved"));
    },
  });
  const removePoll = useDeletePostPoll(post.id, {
    onSuccess: () => {
      setPollDraft(null);
      toast.success(t("poll.removed"));
    },
  });
  // `is_locked`, not a count: a poll whose results are withheld has none.
  const answered = post.poll?.is_locked ?? false;
  return (
    <div className="space-y-2">
      {post.poll && pollDraft === null && <PostPoll post={post} />}
      {canEdit && !preview ? (
        pollDraft === null ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setPollDraft(post.poll ? pollDraftFromRead(post.poll) : emptyPollDraft())
            }
            className="inline-flex items-center gap-2"
          >
            <Vote className="h-4 w-4" aria-hidden />
            {post.poll ? t("poll.edit") : t("poll.add")}
          </Button>
        ) : (
          <>
            <PollEditor
              idPrefix="post-poll"
              value={pollDraft}
              onChange={setPollDraft}
              choicesLocked={answered}
              anonymityLocked={answered && (post.poll?.is_anonymous ?? false)}
              onRemove={post.poll ? () => removePoll.mutate() : undefined}
            />
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setPollDraft(null)}>
                {t("common:cancel")}
              </Button>
              <Button
                size="sm"
                disabled={savePoll.isPending || !isPollDraftValid(pollDraft)}
                onClick={() => savePoll.mutate(pollDraftToWrite(pollDraft))}
              >
                {savePoll.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {savePoll.isPending ? t("saving") : t("common:save")}
              </Button>
            </div>
          </>
        )
      ) : null}
    </div>
  );
};

/** Its tags, each opening every item that carries it. Changed in its header. */
const Tags = ({ item: post }: { item: PostRead }) => {
  const gp = useCommunityPath();
  return post.tags.length > 0 ? (
    <div className="flex flex-wrap gap-1">
      {post.tags.map((tag) => (
        <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
      ))}
    </div>
  ) : null;
};

/** Holds the notice's drafts above its layout, and asks before leaving them. */
const PostShell = ({ context, children }: { context: PostLayoutContext; children: ReactNode }) => {
  const [body, setBody] = useState<SerializedEditorState | null>(null);
  const [poll, setPoll] = useState<PollDraft | null>(null);
  const drafts = useMemo(() => ({ body, setBody, poll, setPoll }), [body, poll]);
  const guard = useUnsavedGuard(
    context.canEdit && !context.preview && (body !== null || poll !== null)
  );
  return (
    <Drafts.Provider value={drafts}>
      {children}
      {guard}
    </Drafts.Provider>
  );
};

/** A notice's detail: its tags, its own parts and where it lives. */
export const POST_DETAIL: DetailKind<PostRead, PostLayoutContext, PostUpdate> = {
  spec: POST_LAYOUT,
  fields: postFields,
  namespaces: ["posts", "common"],
  editors: { tags: Tags },
  parts: {
    byline: (_node, post) => <Byline post={post} />,
    schedule: (_node, post) => <Schedule post={post} />,
    body: (_node, post) => <Body post={post} />,
    reactions: (_node, post) => <Reactions post={post} />,
    poll: (_node, post) => <Poll post={post} />,
    comments: (_node, post) => <ToolCommentsPanel tool={Tool.post} entity={post} />,
  },
  home: (post, context) => ({
    saves: POST_SAVES,
    readOnly: !context.canEdit || Boolean(context.preview),
    initiativeId: post.initiative_id,
    canOpen: { tool: Tool.post, id: post.id },
    links: { entity: post, title: post.name },
  }),
  Shell: PostShell,
  filled: filledBy<PostRead>({ tags: (post) => post.tags.length > 0 }, (post) => post.properties),
};
