import { useBlocker } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { Loader2, Vote } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type PostRead,
  type ResourceGrantSchema,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import {
  emptyPollDraft,
  isPollDraftValid,
  type PollDraft,
  PollEditor,
  pollDraftToWrite,
} from "@/components/initiativeTools/posts/PollEditor";
import {
  EMPTY_REQUIRED,
  missingIn,
  RequiredValues,
  useRequiredKeys,
  valuesOf,
} from "@/components/layouts/RequiredValues";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCreatePost } from "@/hooks/usePosts";
import { useProperties } from "@/hooks/useProperties";
import { sharedTarget } from "@/hooks/useToolLayouts";
import { fromLocalDateTimeInput } from "@/lib/formatDate";
import { MAX_POST_TEXT_CHARS } from "@/lib/posts";
import type { DialogProps } from "@/types/dialog";

const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);

type CreatePostDialogProps = DialogProps & {
  initiativeId: number;
  onSuccess?: (post: PostRead) => void;
};

/**
 * Writing a notice.
 *
 * Deliberately not the shared `CreateToolDialog`: every other tool is created
 * by naming an empty container, but a post IS its content — there is nothing
 * to create before it is written. So the body is here, in the full editor,
 * rather than on a page you reach afterwards.
 */
export const CreatePostDialog = ({
  open,
  onOpenChange,
  initiativeId,
  onSuccess,
}: CreatePostDialogProps) => {
  const { t } = useTranslation(["posts", "common", "access", "layouts"]);
  const [name, setName] = useState("");
  const [body, setBody] = useState<SerializedEditorState | null>(null);
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);
  // Empty means "post it now", which is what most notices are. A value here
  // holds the notice back: nobody sees it and nobody is told until then.
  const [scheduledFor, setScheduledFor] = useState("");
  // Null means the notice asks nothing, which is what most notices do. The
  // section below is opened by a button rather than always shown, so the
  // common case is not a form somebody has to scroll past.
  const [poll, setPoll] = useState<PollDraft | null>(null);
  // What the initiative's posts page requires of a notice, asked for here
  // because nothing else in this form sets it.
  const required = useRequiredKeys(open ? sharedTarget(Tool.post, initiativeId) : null, "post");
  const definitions = useProperties({ initiativeId, enabled: open }).data;
  const [values, setValues] = useState(EMPTY_REQUIRED);
  const missing = missingIn(required.keys, values, definitions);

  useEffect(() => {
    if (!open) {
      setName("");
      setBody(null);
      setGrants([...DEFAULT_GRANTS]);
      setScheduledFor("");
      setPoll(null);
      setValues(EMPTY_REQUIRED);
    }
  }, [open]);

  const create = useCreatePost({
    onSuccess: (post) => {
      onOpenChange(false);
      onSuccess?.(post);
    },
  });

  // A half-written poll blocks the post rather than being quietly dropped:
  // somebody who started one meant to ask something.
  const canSubmit =
    name.trim().length > 0 &&
    !create.isPending &&
    (poll === null || isPollDraftValid(poll)) &&
    !required.isLoading &&
    missing.length === 0;

  // A composer full of links, mentions and chips is a composer full of things
  // that navigate, and navigating away closes the dialog with the whole
  // unwritten post inside it. Ask first — but only while there is something to
  // lose, and never once the post has been created.
  const isDirty =
    open &&
    !create.isPending &&
    (name.trim().length > 0 || body !== null || scheduledFor !== "" || poll !== null);
  // `enableBeforeUnload` is not optional in practice: the router defaults it to
  // TRUE and never consults `shouldBlockFn` for a reload, so a mounted blocker
  // prompts "Changes you made may not be saved" on every refresh. This dialog
  // is rendered by the board whether it is open or not, which made that every
  // refresh of the board.
  const blocker = useBlocker({
    shouldBlockFn: () => isDirty,
    enableBeforeUnload: () => isDirty,
    withResolver: true,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("createPost")}</DialogTitle>
          <DialogDescription>{t("noPostsDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="create-post-name">{t("name")}</Label>
            <Input
              id="create-post-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              maxLength={255}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-post-body">{t("body")}</Label>
            {/* `bg-card`, like the board: what you are writing should look
                like what you are about to post. */}
            <div id="create-post-body" className="rounded-md border bg-card">
              <Suspense fallback={<Skeleton className="h-40 w-full" />}>
                <Editor
                  onSerializedChange={setBody}
                  initiativeId={initiativeId}
                  supportsEntityMentions
                  variant="post"
                  maxLength={MAX_POST_TEXT_CHARS}
                />
              </Suspense>
            </div>
          </div>

          <RequiredValues
            keys={required.keys}
            definitions={definitions ?? []}
            draft={values}
            onChange={setValues}
            initiativeId={initiativeId}
            idPrefix="create-post"
          />

          <div className="space-y-2">
            {poll === null ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPoll(emptyPollDraft())}
              >
                <Vote className="size-4" aria-hidden />
                {t("poll.add")}
              </Button>
            ) : (
              <PollEditor
                idPrefix="create-post-poll"
                value={poll}
                onChange={setPoll}
                onRemove={() => setPoll(null)}
              />
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-post-schedule">{t("schedule.label")}</Label>
            <DateTimePicker
              id="create-post-schedule"
              includeTime
              value={scheduledFor}
              placeholder={t("schedule.placeholder")}
              onChange={setScheduledFor}
            />
            <p className="text-muted-foreground text-xs">{t("schedule.hint")}</p>
          </div>

          <CreateAccessSection initiativeId={initiativeId} grants={grants} onChange={setGrants} />
        </div>

        <DialogFooter className="items-center">
          {missing.length > 0 ? (
            <p className="text-muted-foreground text-xs">{t("layouts:required.toAdd")}</p>
          ) : null}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={!canSubmit}
            onClick={() =>
              create.mutate({
                name: name.trim(),
                initiative_id: initiativeId,
                body: { ...body },
                grants,
                scheduled_for: fromLocalDateTimeInput(scheduledFor),
                poll: poll ? pollDraftToWrite(poll) : null,
                tag_ids: values.tags.map((tag) => tag.id),
                properties: valuesOf(values),
              })
            }
          >
            {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {create.isPending
              ? t("creating")
              : scheduledFor
                ? t("schedule.submit")
                : t("createPost")}
          </Button>
        </DialogFooter>
      </DialogContent>

      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(next) => {
          if (!next) blocker.reset?.();
        }}
        title={t("unsaved.title")}
        description={t("unsaved.body")}
        confirmLabel={t("unsaved.leave")}
        cancelLabel={t("unsaved.stay")}
        onConfirm={() => blocker.proceed?.()}
        destructive
      />
    </Dialog>
  );
};
