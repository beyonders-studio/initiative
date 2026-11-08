/**
 * What feedback asks for, in the sheet and on Initiative Cloud's page: the
 * kind first, an idea to start, which picks the question the box asks and
 * keeps what was written when it changes; the box, with pictures where they
 * are taken; whether the team may contact the sender; and the device and page
 * it was sent from, theirs to leave out. Once sent, the thanks.
 */

import { CircleAlert, Heart, Lightbulb, type LucideIcon } from "lucide-react";
import type { ComponentProps, ElementType, Ref } from "react";
import { useTranslation } from "react-i18next";

import {
  type DeviceContext,
  type EvidencePolicyRead,
  FeedbackTopic,
  SupportTopic,
} from "@/api/generated/initiativeAPI.schemas";
import proudSvg from "@/assets/yonder/proud.svg";
import talkingSvg from "@/assets/yonder/talking.svg";
import { HelpLink } from "@/components/support/HelpLink";
import { DeviceContextSwitch } from "@/components/tickets/DeviceContext";
import { TicketComposer } from "@/components/tickets/TicketComposer";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** Match the column behind it, so the box stops where the server would. */
const BODY_MAX = 5000;

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
}

export const EMPTY_DRAFT: FeedbackDraft = {
  kind: FeedbackTopic.idea,
  body: "",
  contactable: false,
  withContext: true,
  files: [],
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
        <div className="space-y-1.5">
          <Label htmlFor="feedback-body">{t(`feedback.kinds.${draft.kind}.question`)}</Label>
          <TicketComposer
            ref={box}
            id="feedback-body"
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
        </div>
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
