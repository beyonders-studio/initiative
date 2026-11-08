/**
 * Filing a ticket: reporting something, a security problem, or feedback.
 * Help requests are asked from the Help panel (`components/help/HelpPanel`);
 * a feedback problem that needs an answer is sent as one from here.
 *
 * One dialog for these kinds, opened by whatever surface files one — a Report
 * flag, the security report, the feedback sheet. Each kind brings its own
 * fields; sending, the acknowledgement and the fallback are shared.
 *
 * What comes back is an acknowledgement and nothing else. A report in
 * particular never says where it went, whether somebody had already reported
 * the same thing, or what happens next: a report is not a conversation with
 * the person who sent it.
 *
 * Where a report has to go to the people who run the deployment and they have
 * set nothing up to receive it, the dialog turns into their address, if they
 * gave one, rather than ending on a refusal.
 *
 * A report of something illegal names the law and says what is wrong; it goes
 * to the community and to the people who run the server at once, and where
 * they take no reports here, the thanks says how to reach them. A child-safety
 * report carries no files: it says where the material is, and it stays there.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DeviceContext,
  FeedbackTopic,
  LegalBasis,
  ReportReason,
  SecurityTopic,
  SupportTopic,
} from "@/api/generated/initiativeAPI.schemas";
import {
  LegalBasis as Basis,
  FeedbackTopic as Feedback,
  ReportReason as Reason,
  SupportTopic as Support,
  SecurityTopic as Topic,
} from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { DeviceContextPreview } from "@/components/tickets/DeviceContext";
import { EvidencePicker, fitToPolicy } from "@/components/tickets/Evidence";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  COMMUNITY_TOPICS,
  firstLine,
  SUBJECT_MAX,
  type TicketCreate,
  useFileTicket,
  useTicketAvailability,
} from "@/hooks/useTickets";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { listFormat } from "@/lib/intl";
import { toast } from "@/lib/mascotToast";

/** Match the columns behind them, so a field stops where the server would. */
const BODY_MAX = 5000;
const DETAIL_MAX = 4000;

/** The reasons, in the order they are offered. */
const REASONS: ReportReason[] = [
  Reason.harassment,
  Reason.hate,
  Reason.violence,
  Reason.sexual_content,
  Reason.self_harm,
  Reason.illegal,
  Reason.spam,
  Reason.misinformation,
  Reason.other,
];

/** The laws an illegal report can name, in the order they are offered. */
const BASES: LegalBasis[] = [
  Basis.child_safety,
  Basis.terrorism,
  Basis.privacy,
  Basis.fraud,
  Basis.intellectual_property,
  Basis.other,
];

/** What a security report can be about, in the order they are offered. */
const SECURITY_TOPICS: SecurityTopic[] = [
  Topic.vulnerability,
  Topic.account_compromise,
  Topic.other,
];

/** What feedback can be, in the order it is offered. */
const FEEDBACK_TOPICS: FeedbackTopic[] = [
  Feedback.idea,
  Feedback.problem,
  Feedback.praise,
  Feedback.other,
];

/** What is being filed. */
export type TicketKind =
  | { stream: "security" }
  | {
      stream: "feedback";
      /** Where the app was, shown before sending and removable. */
      context?: DeviceContext;
    }
  | {
      stream: "moderation";
      /** A `SearchEntityType` or a `PlatformReportTarget` value. */
      targetType: string;
      targetId: number;
    };

export interface FileTicketDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticket: TicketKind;
  /** The community the reader is standing in, when they are in one. Asking
   *  for help is always from one; a report may come from nowhere. */
  communityId: number | null;
}

export const FileTicketDialog = ({
  open,
  onOpenChange,
  ticket,
  communityId,
}: FileTicketDialogProps) => {
  const { t } = useTranslation(["intake", "moderation", "common"]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState<ReportReason | "">("");
  const [basis, setBasis] = useState<LegalBasis | "">("");
  const [topic, setTopic] = useState<SecurityTopic | "">("");
  const [feedbackType, setFeedbackType] = useState<FeedbackTopic | "">("");
  const [needsAnswer, setNeedsAnswer] = useState(false);
  const [context, setContext] = useState<DeviceContext | null>(
    ticket.stream === "feedback" ? (ticket.context ?? null) : null
  );
  const [files, setFiles] = useState<File[]>([]);
  // What was taken back off because the form stopped taking it.
  const [dropped, setDropped] = useState<string[]>([]);
  // Set, to what the server said, when the people who run the deployment had
  // nowhere to receive this. Kept apart from their address, which may still
  // be on its way: the dialog turns into the address whenever it arrives, and
  // says why it could not send only where there is no address at all.
  const [nowhere, setNowhere] = useState<string | null>(null);
  const availability = useTicketAvailability(communityId, { enabled: open });
  const supportOffer = availability.data?.support;
  const helpTopics = (supportOffer?.types ?? []) as SupportTopic[];

  const isReport = ticket.stream === "moderation";
  const isSecurity = ticket.stream === "security";
  const isFeedback = ticket.stream === "feedback";
  // A problem that needs an answer is a help request, not feedback: sent to
  // support instead, where somebody writes back.
  const canAskInstead = isFeedback && supportOffer?.mode === "form" && helpTopics.length > 0;
  const askingInstead = canAskInstead && feedbackType === Feedback.problem && needsAnswer;
  const sentAs = askingInstead ? "support" : ticket.stream;
  const contact = availability.data?.[sentAs]?.contact ?? null;
  const evidence = availability.data?.[sentAs]?.evidence ?? null;

  // A feedback sent as a help request takes support's files; unticking that
  // puts feedback's back, and whatever it does not take comes off, said so,
  // rather than refusing the whole send.
  useEffect(() => {
    if (!evidence) return;
    const { kept, dropped: off } = fitToPolicy(files, evidence);
    if (off.length === 0) return;
    setFiles(kept);
    setDropped(off.map((file) => file.name));
  }, [evidence, files]);
  const illegal = reason === Reason.illegal;
  // An illegal or "something else" report has to say what is wrong.
  const detailRequired = illegal || reason === Reason.other;
  const childSafety = illegal && basis === Basis.child_safety;

  const file = useFileTicket({
    onSuccess: (accepted) => {
      const contactLine = accepted.platform_contact
        ? t("moderation:report.platformContact", { contact: accepted.platform_contact })
        : undefined;
      toast.success(
        isReport
          ? t("moderation:report.thanks")
          : isSecurity
            ? t("security.thanks")
            : isFeedback && !askingInstead
              ? t("feedback.thanks")
              : t("help.thanks"),
        contactLine ? { description: contactLine } : undefined
      );
      onOpenChange(false);
      setSubject("");
      setBody("");
      setReason("");
      setBasis("");
      setTopic("");
      setFeedbackType("");
      setNeedsAnswer(false);
      setFiles([]);
    },
    onError: (err) => {
      const message = getErrorMessage(
        err,
        isReport
          ? "moderation:report.error"
          : isSecurity
            ? "intake:security.error"
            : isFeedback && !askingInstead
              ? "intake:feedback.error"
              : "intake:help.error"
      );
      if (getHttpStatus(err) === 503) {
        setNowhere(message);
        return;
      }
      toast.error(message);
    },
  });

  if (nowhere && contact) {
    // What they wrote goes with them, so falling back to email does not mean
    // writing it again.
    const draft =
      ticket.stream === "moderation"
        ? {
            subject: reason
              ? `${t("moderation:report.title")}: ${t(`moderation:reasons.${reason}`)}`
              : t("moderation:report.title"),
            body: [body.trim(), `${ticket.targetType} ${ticket.targetId}`]
              .filter(Boolean)
              .join("\n\n"),
          }
        : ticket.stream === "feedback"
          ? {
              subject: feedbackType
                ? `${t("feedback.title")}: ${t(`feedback.topics.${feedbackType}`)}`
                : t("feedback.title"),
              body: body.trim(),
            }
          : { subject: subject.trim(), body: body.trim() };
    return (
      <ContactDialog open={open} onOpenChange={onOpenChange} contact={contact} draft={draft} />
    );
  }

  const payload = (): TicketCreate | null => {
    if (ticket.stream === "moderation") {
      if (!reason) return null;
      if (illegal && !basis) return null;
      if (detailRequired && !body.trim()) return null;
      return {
        stream: "moderation",
        target_type: ticket.targetType,
        target_id: ticket.targetId,
        reason,
        detail: body.trim() || null,
        legal_basis: illegal && basis ? basis : null,
        community_id: communityId,
      };
    }
    if (ticket.stream === "security") {
      if (!topic || !subject.trim() || !body.trim()) return null;
      return { stream: "security", type: topic, subject: subject.trim(), body: body.trim() };
    }
    if (ticket.stream === "feedback") {
      if (!feedbackType || !body.trim()) return null;
      if (askingInstead) {
        // About the community it was sent from where that is a question the
        // reader may ask here; about themselves otherwise.
        const about =
          communityId != null && helpTopics.includes(Support.community)
            ? Support.community
            : helpTopics.includes(Support.account)
              ? Support.account
              : (helpTopics[0] ?? Support.account);
        return {
          stream: "support",
          type: about,
          community_id: COMMUNITY_TOPICS.has(about) ? communityId : null,
          subject: firstLine(body),
          body: body.trim(),
        };
      }
      return {
        stream: "feedback",
        type: feedbackType,
        body: body.trim(),
        context,
      };
    }
    return null;
  };
  const ready = payload();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isReport
              ? t("moderation:report.title")
              : isSecurity
                ? t("security.title")
                : t("feedback.title")}
          </DialogTitle>
          <DialogDescription>
            {isReport
              ? t("moderation:report.description")
              : isSecurity
                ? t("security.description")
                : t("feedback.description")}
          </DialogDescription>
        </DialogHeader>

        {isReport ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ticket-reason">{t("moderation:report.reasonLabel")}</Label>
              <Select value={reason} onValueChange={(v) => setReason(v as ReportReason)}>
                <SelectTrigger id="ticket-reason">
                  <SelectValue placeholder={t("moderation:report.reasonPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {REASONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`moderation:reasons.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {illegal && (
              <div className="space-y-2">
                <Label htmlFor="ticket-basis">{t("moderation:report.basisLabel")}</Label>
                <Select
                  value={basis}
                  onValueChange={(v) => {
                    setBasis(v as LegalBasis);
                    // Nothing is attached to a child-safety report.
                    if (v === Basis.child_safety) setFiles([]);
                  }}
                >
                  <SelectTrigger id="ticket-basis">
                    <SelectValue placeholder={t("moderation:report.basisPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {BASES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(`moderation:hold.bases.${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">
                  {childSafety
                    ? t("moderation:report.childSafetyHelp")
                    : t("moderation:report.basisHelp")}
                </p>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="ticket-detail">
                {detailRequired
                  ? t("moderation:report.detailRequiredLabel")
                  : t("moderation:report.detailLabel")}
              </Label>
              <Textarea
                id="ticket-detail"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={
                  detailRequired
                    ? t("moderation:report.detailRequiredPlaceholder")
                    : t("moderation:report.detailPlaceholder")
                }
                rows={4}
                maxLength={DETAIL_MAX}
              />
            </div>
          </div>
        ) : isFeedback ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ticket-feedback-type">{t("feedback.typeLabel")}</Label>
              <Select
                value={feedbackType}
                onValueChange={(v) => setFeedbackType(v as FeedbackTopic)}
              >
                <SelectTrigger id="ticket-feedback-type">
                  <SelectValue placeholder={t("feedback.typePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {FEEDBACK_TOPICS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`feedback.topics.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ticket-body">{t("feedback.bodyLabel")}</Label>
              <Textarea
                id="ticket-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={t("feedback.bodyPlaceholder")}
                rows={6}
                maxLength={BODY_MAX}
              />
            </div>
            {canAskInstead && feedbackType === Feedback.problem ? (
              <div className="flex items-start gap-2">
                <Checkbox
                  id="ticket-needs-answer"
                  checked={needsAnswer}
                  onCheckedChange={(checked) => setNeedsAnswer(checked === true)}
                />
                <div className="space-y-1">
                  <Label htmlFor="ticket-needs-answer">{t("feedback.needsAnswer")}</Label>
                  <p className="text-muted-foreground text-xs">{t("feedback.needsAnswerHelp")}</p>
                </div>
              </div>
            ) : null}
            {context && !askingInstead ? (
              <DeviceContextPreview context={context} onRemove={() => setContext(null)} />
            ) : null}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ticket-topic">{t("security.topicLabel")}</Label>
              <Select value={topic} onValueChange={(v) => setTopic(v as SecurityTopic)}>
                <SelectTrigger id="ticket-topic">
                  <SelectValue placeholder={t("security.topicPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {SECURITY_TOPICS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`intake:security.topics.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ticket-subject">{t("help.subjectLabel")}</Label>
              <Input
                id="ticket-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t("help.subjectPlaceholder")}
                maxLength={SUBJECT_MAX}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ticket-body">{t("security.bodyLabel")}</Label>
              <Textarea
                id="ticket-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={t("security.bodyPlaceholder")}
                rows={6}
                maxLength={BODY_MAX}
              />
            </div>
            {/* A report about this server stays here; one about the software
                itself goes to the project. */}
            <p className="text-muted-foreground text-xs">{t("security.softwareNote")}</p>
          </div>
        )}

        {!childSafety && (
          <EvidencePicker
            policy={evidence}
            files={files}
            onChange={setFiles}
            disabled={file.isPending}
          />
        )}

        {dropped.length > 0 && (
          <p className="text-muted-foreground text-sm" role="status">
            {t("evidence.dropped", {
              count: dropped.length,
              names: listFormat(undefined, { type: "conjunction" }).format(dropped),
            })}
          </p>
        )}

        {nowhere && !availability.isPending && (
          <p className="text-destructive text-sm" role="alert">
            {nowhere}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            disabled={!ready || file.isPending}
            onClick={() => ready && file.mutate({ ticket: ready, files })}
          >
            {isReport
              ? t("moderation:report.submit")
              : isSecurity
                ? t("security.submit")
                : isFeedback && !askingInstead
                  ? t("feedback.submit")
                  : t("help.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
