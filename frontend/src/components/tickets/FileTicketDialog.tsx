/**
 * Filing a ticket: asking for help, reporting something, or a security
 * problem.
 *
 * One dialog for every kind, opened by whatever surface files one — the
 * sidebar's "Ask for help", a Report flag, a status notice. Each kind brings
 * its own fields; sending, the acknowledgement and the fallback are shared.
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

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  LegalBasis,
  ReportReason,
  SecurityTopic,
  SupportTopic,
} from "@/api/generated/initiativeAPI.schemas";
import {
  LegalBasis as Basis,
  ReportReason as Reason,
  SupportTopic as Support,
  SecurityTopic as Topic,
} from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { EvidencePicker } from "@/components/tickets/Evidence";
import {
  FAQ_URL,
  type TicketCreate,
  useFileTicket,
  useTicketAvailability,
} from "@/hooks/useTickets";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Textarea } from "@/ui/textarea";

/** Match the columns behind them, so a field stops where the server would. */
const SUBJECT_MAX = 200;
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

/** The help a person asks for about a community, rather than themselves. */
const COMMUNITY_TOPICS: ReadonlySet<string> = new Set([Support.community, Support.data_request]);

/** What is being filed. */
export type TicketKind =
  | {
      stream: "support";
      /** The topic to start on, where the surface knows what it is about.
       *  Falls back to the first one offered here when it is not. */
      topic?: SupportTopic;
    }
  | { stream: "security" }
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
  const [chosenHelpTopic, setHelpTopic] = useState<SupportTopic | "">(
    ticket.stream === "support" ? (ticket.topic ?? "") : ""
  );
  const [files, setFiles] = useState<File[]>([]);
  // Set, to what the server said, when the people who run the deployment had
  // nowhere to receive this. Kept apart from their address, which may still
  // be on its way: the dialog turns into the address whenever it arrives, and
  // says why it could not send only where there is no address at all.
  const [nowhere, setNowhere] = useState<string | null>(null);
  const availability = useTicketAvailability(communityId, { enabled: open });
  const supportOffer = availability.data?.support;
  const helpTopics = (supportOffer?.types ?? []) as SupportTopic[];
  // The topic asked for where it is offered here. A question about a
  // community the reader may not ask about from here — it is closed to them,
  // or takes no help requests — opens on "something else", which they may;
  // otherwise the first topic that is offered.
  const helpTopic: SupportTopic | "" =
    chosenHelpTopic && helpTopics.includes(chosenHelpTopic)
      ? chosenHelpTopic
      : chosenHelpTopic &&
          COMMUNITY_TOPICS.has(chosenHelpTopic) &&
          helpTopics.includes(Support.other)
        ? Support.other
        : (helpTopics[0] ?? "");

  const isReport = ticket.stream === "moderation";
  const isSecurity = ticket.stream === "security";
  const contact = availability.data?.[ticket.stream]?.contact ?? null;
  const evidence = availability.data?.[ticket.stream]?.evidence ?? null;
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
            : t("help.thanks"),
        contactLine ? { description: contactLine } : undefined
      );
      onOpenChange(false);
      setSubject("");
      setBody("");
      setReason("");
      setBasis("");
      setTopic("");
      setFiles([]);
    },
    onError: (err) => {
      const message = getErrorMessage(
        err,
        isReport
          ? "moderation:report.error"
          : isSecurity
            ? "intake:security.error"
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
    if (!helpTopic || !subject.trim() || !body.trim()) return null;
    const aboutCommunity = COMMUNITY_TOPICS.has(helpTopic);
    if (aboutCommunity && communityId == null) return null;
    return {
      stream: "support",
      type: helpTopic,
      community_id: aboutCommunity ? communityId : null,
      subject: subject.trim(),
      body: body.trim(),
    };
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
                : t("help.title")}
          </DialogTitle>
          <DialogDescription>
            {isReport
              ? t("moderation:report.description")
              : isSecurity
                ? t("security.description")
                : t("help.description")}
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
        ) : (
          <div className="space-y-4">
            {!isSecurity && helpTopics.length > 1 && (
              <div className="space-y-2">
                <Label htmlFor="ticket-help-topic">{t("help.topicLabel")}</Label>
                <Select value={helpTopic} onValueChange={(v) => setHelpTopic(v as SupportTopic)}>
                  <SelectTrigger id="ticket-help-topic">
                    <SelectValue placeholder={t("help.topicPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {helpTopics.map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(`help.topics.${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {isSecurity && (
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
            )}
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
              <Label htmlFor="ticket-body">
                {isSecurity ? t("security.bodyLabel") : t("help.bodyLabel")}
              </Label>
              <Textarea
                id="ticket-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={isSecurity ? t("security.bodyPlaceholder") : t("help.bodyPlaceholder")}
                rows={6}
                maxLength={BODY_MAX}
              />
            </div>
            {/* A report about this server stays here; one about the software
                itself goes to the project. */}
            {isSecurity ? (
              <p className="text-muted-foreground text-xs">{t("security.softwareNote")}</p>
            ) : null}
            {/* The FAQ is still the faster answer for most of what gets asked,
                so it stays one click away from the form. */}
            <p className="text-muted-foreground text-xs">
              <a
                href={FAQ_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-foreground"
              >
                {t("help.browseFaq")}
              </a>
            </p>
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
                : t("help.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
