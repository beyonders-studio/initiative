/**
 * What feedback asks for, in the sheet and on Initiative Cloud's page: the
 * kind first, an idea to start, which picks the question the box asks and
 * keeps what was written when it changes; the box, with pictures where they
 * are taken, and under an idea the published ideas like it; whether the team
 * may contact the sender; and the device and page it was sent from, theirs to
 * leave out. Once sent, the thanks.
 */

import { Link } from "@tanstack/react-router";
import { CircleAlert, Heart, Lightbulb, type LucideIcon } from "lucide-react";
import type { ComponentProps, ElementType, Ref } from "react";
import { useTranslation } from "react-i18next";

import {
  type DeviceContext,
  type EvidencePolicyRead,
  type FeedbackTicketCreate,
  FeedbackTopic,
  SupportTopic,
} from "@/api/generated/initiativeAPI.schemas";
import proudSvg from "@/assets/yonder/proud.svg";
import talkingSvg from "@/assets/yonder/talking.svg";
import { IdeaStatusBadge, VoteButton } from "@/components/ideas/IdeaParts";
import { HelpLink } from "@/components/support/HelpLink";
import { DeviceContextSwitch } from "@/components/tickets/DeviceContext";
import { TicketComposer } from "@/components/tickets/TicketComposer";
import { useSimilarIdeas } from "@/hooks/useIdeas";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** Match the column behind it, so the box stops where the server would. */
const BODY_MAX = 5000;

/** How much of what is written the ideas like it are found by, as the
 *  server takes it: an idea is said at the start. */
const MATCH_TEXT = 1000;
/** How many words are written before ideas like them are looked for. */
const MATCH_WORDS = 3;

/** The kinds, in the order they are offered, each with its picture. */
const KINDS: [FeedbackTopic, LucideIcon][] = [
  [FeedbackTopic.idea, Lightbulb],
  [FeedbackTopic.problem, CircleAlert],
  [FeedbackTopic.praise, Heart],
];

export interface FeedbackDraft {
  kind: FeedbackTopic;
  body: string;
  contactable: boolean;
  withContext: boolean;
  files: File[];
  /** The published idea voted for while writing, which sending joins. */
  idea?: { task_id: number; title: string } | null;
}

export const EMPTY_DRAFT: FeedbackDraft = {
  kind: FeedbackTopic.idea,
  body: "",
  contactable: false,
  withContext: true,
  files: [],
  idea: null,
};

/** What sending `draft` files. */
export const feedbackTicket = (
  draft: FeedbackDraft,
  context: DeviceContext | null
): FeedbackTicketCreate => ({
  stream: "feedback",
  type: draft.kind,
  body: draft.body.trim(),
  contactable: draft.contactable,
  context: draft.withContext ? context : null,
  idea_task_id: draft.kind === FeedbackTopic.idea ? (draft.idea?.task_id ?? null) : null,
});

/**
 * The open published ideas like what is being written. Voting for one keeps
 * it on the draft, so sending joins what was written to it.
 */
const IdeasLikeThis = ({
  draft,
  onChange,
  onSignIn,
}: {
  draft: FeedbackDraft;
  onChange: (next: Partial<FeedbackDraft>) => void;
  onSignIn?: () => void;
}) => {
  const { t } = useTranslation("intake");
  const text = useDebouncedValue(draft.body.trim().slice(0, MATCH_TEXT), 400);
  const enough = text.split(/\s+/).filter(Boolean).length >= MATCH_WORDS;
  const { data: matches = [] } = useSimilarIdeas(enough ? text : "");
  if (!matches.length && !draft.idea) return null;
  return (
    <div className="space-y-2">
      <p className="font-medium text-sm">{t("feedback.matches")}</p>
      <ul className="space-y-1.5">
        {matches.map((idea) => (
          <li key={idea.task_id} className="flex items-center gap-3 rounded-md border px-3 py-2">
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="font-medium text-sm">{idea.title}</p>
              <div className="flex flex-wrap items-center gap-2 text-muted-foreground text-xs">
                <IdeaStatusBadge status={idea.status} />
                <span>{t("ideas.votes", { count: idea.votes })}</span>
              </div>
            </div>
            <VoteButton
              idea={idea}
              next="/feedback"
              onSignIn={onSignIn}
              onVoted={(on) =>
                onChange({
                  idea: on
                    ? { task_id: idea.task_id, title: idea.title }
                    : draft.idea?.task_id === idea.task_id
                      ? null
                      : draft.idea,
                })
              }
            />
          </li>
        ))}
      </ul>
      {draft.idea ? (
        <p className="text-muted-foreground text-xs">
          {t("feedback.joins", { title: draft.idea.title })}
        </p>
      ) : null}
    </div>
  );
};

interface FeedbackFormProps {
  /** The heading's element: the sheet's title, or the page's. */
  Title: ElementType;
  draft: FeedbackDraft;
  onChange: (next: Partial<FeedbackDraft>) => void;
  onDiscard: () => void;
  /** Where it is sent from, or null where nothing travels with it. */
  context: DeviceContext | null;
  /** What may be attached, or null where pictures are not taken. */
  evidence: EvidencePolicyRead | null | undefined;
  /** A picture of the page behind, where the form is over one. */
  pagePicture?: ComponentProps<typeof TicketComposer>["pagePicture"];
  /** The community a problem's "ask for help" is asked in; left out, the
   *  form offers no help. */
  help?: { communityId: number | null };
  /** Keeps the draft and sends somebody signed out to sign in, where voting
   *  for an idea like theirs would otherwise lose it. */
  onSignIn?: () => void;
  pending: boolean;
  sent: boolean;
  /** What the send button says. */
  submitLabel: string;
  onSend: () => void;
  onDone: () => void;
  box?: Ref<HTMLTextAreaElement>;
  thanks?: Ref<HTMLHeadingElement>;
}

export const FeedbackForm = ({
  Title,
  draft,
  onChange,
  onDiscard,
  context,
  evidence,
  pagePicture,
  help,
  onSignIn,
  pending,
  sent,
  submitLabel,
  onSend,
  onDone,
  box,
  thanks,
}: FeedbackFormProps) => {
  const { t } = useTranslation("intake");
  const written = Boolean(draft.body.trim());

  if (sent) {
    return (
      <div role="status" className="flex flex-col items-center gap-2 px-6 pt-8 pb-6 text-center">
        <img src={proudSvg} alt="" className="size-20" />
        <Title ref={thanks} tabIndex={-1} className="font-semibold text-lg outline-none">
          {t("feedback.thanks")}
        </Title>
        <p className="text-muted-foreground text-sm">{t("feedback.thanksBody")}</p>
        <Button type="button" variant="outline" size="sm" className="mt-2" onClick={onDone}>
          {t("feedback.done")}
        </Button>
      </div>
    );
  }

  const send = () => {
    if (written && !pending) onSend();
  };

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          send();
        }
      }}
    >
      <div className="flex items-center gap-3 py-4 pr-12 pl-4">
        <img src={talkingSvg} alt="" className="size-11 shrink-0" />
        <Title className="font-semibold text-base leading-snug">{t("feedback.title")}</Title>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        <ToggleGroup
          type="single"
          variant="outline"
          size="tile"
          aria-label={t("feedback.kindLabel")}
          className="grid grid-cols-3 gap-1.5"
          value={draft.kind}
          // A kind is always chosen: choosing it again keeps it.
          onValueChange={(kind) => kind && onChange({ kind: kind as FeedbackTopic })}
          disabled={pending}
        >
          {KINDS.map(([kind, Icon]) => (
            <ToggleGroupItem key={kind} value={kind}>
              <Icon aria-hidden />
              {t(`feedback.kinds.${kind}.label`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Field label={t(`feedback.kinds.${draft.kind}.question`)} className="space-y-1.5">
          <TicketComposer
            ref={box}
            rows={4}
            maxLength={BODY_MAX}
            value={draft.body}
            onChange={(event) => onChange({ body: event.target.value })}
            placeholder={t(`feedback.kinds.${draft.kind}.placeholder`)}
            policy={evidence}
            files={draft.files}
            onFilesChange={(files) => onChange({ files })}
            pagePicture={pagePicture}
            disabled={pending}
          />
        </Field>
        <div className="flex items-center gap-2">
          <Checkbox
            id="feedback-contactable"
            checked={draft.contactable}
            onCheckedChange={(checked) => onChange({ contactable: checked === true })}
            disabled={pending}
          />
          <Label htmlFor="feedback-contactable" className="font-normal">
            {t("feedback.contactable")}
          </Label>
        </div>
        {draft.kind === FeedbackTopic.idea ? (
          <IdeasLikeThis draft={draft} onChange={onChange} onSignIn={onSignIn} />
        ) : null}
        {/* An idea may already be on the Ideas page, waiting for a vote. */}
        {draft.kind === FeedbackTopic.idea ? (
          <Link
            to="/ideas"
            className="inline-block text-muted-foreground text-sm underline underline-offset-2 hover:text-foreground"
          >
            {t("feedback.seeIdeas")}
          </Link>
        ) : null}
        {/* Somebody who needs it sorted needs an answer, which feedback is not. */}
        {help && draft.kind === FeedbackTopic.problem ? (
          <HelpLink
            topic={SupportTopic.other}
            communityId={help.communityId}
            label={t("feedback.stuck")}
          />
        ) : null}
      </div>

      <div className="space-y-2 border-t px-4 py-3">
        {context ? (
          <DeviceContextSwitch
            context={context}
            included={draft.withContext}
            onIncludedChange={(withContext) => onChange({ withContext })}
            disabled={pending}
          />
        ) : null}
        <div className="flex items-center gap-2">
          {written || draft.files.length ? (
            <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={onDiscard}>
              {t("feedback.discard")}
            </Button>
          ) : null}
          <span className="min-w-0 flex-1 text-muted-foreground text-xs" aria-live="polite">
            {written ? "" : t("feedback.writeSomething")}
          </span>
          <Button type="submit" size="sm" disabled={!written || pending}>
            {submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
};
