/**
 * Filing a ticket: reporting something, or a security problem. Help requests
 * are asked from Help (`components/help/HelpPanel`), and feedback from its
 * own sheet.
 *
 * One dialog for both, opened by a Report flag or the security report: a
 * report is about one thing, already chosen, so it holds the page still while
 * it is written. Each kind brings its own fields; sending, the thanks and the
 * fallback are shared.
 *
 * Once sent, the dialog thanks the reporter and, where the server gave one,
 * shows an address to write to as well.
 *
 * Where the server takes no reports here but gave an address, the dialog
 * becomes that address, with what was written.
 *
 * A report of something illegal names the law and says what is wrong. A
 * child-safety report takes no files.
 */

import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  LegalBasis,
  ReportReason,
  SecurityTopic,
} from "@/api/generated/initiativeAPI.schemas";
import {
  LegalBasis as Basis,
  ReportReason as Reason,
  SecurityTopic as Topic,
} from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { TicketComposer } from "@/components/tickets/TicketComposer";
import {
  SUBJECT_MAX,
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/ui/empty";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

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

/** What is being filed. */
export type TicketKind =
  | { stream: "security" }
  | {
      stream: "moderation";
      /** A `SearchEntityType` or a `PlatformReportTarget` value. */
      targetType: string;
      targetId: number;
      /** Where the thing is drawn, pictured as the report opens; the page
       *  where none is marked. */
      thing?: Element | null;
    };

export interface FileTicketDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticket: TicketKind;
  /** The community the reader is standing in, when they are in one; a
   *  report may come from nowhere. */
  communityId: number | null;
}

/** One of several answers, from a dropdown. */
const Choice = <T extends string>({
  id,
  label,
  placeholder,
  value,
  options,
  labelOf,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: T | "";
  options: T[];
  labelOf: (option: T) => string;
  onChange: (option: T) => void;
  disabled?: boolean;
}) => (
  <div className="space-y-1.5">
    <Label htmlFor={id}>{label}</Label>
    <Select value={value} onValueChange={(next) => onChange(next as T)} disabled={disabled}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option} value={option}>
            {labelOf(option)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  </div>
);

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
  const [files, setFiles] = useState<File[]>([]);
  // What the server said when it had nowhere to receive this. The address may
  // arrive after it: the sheet becomes the address once there is one, and
  // shows this line only while there is none.
  const [nowhere, setNowhere] = useState<string | null>(null);
  // Once sent: the address the thanks offers as well, if any.
  const [sent, setSent] = useState<{ elsewhere: string | null } | null>(null);
  const thanks = useRef<HTMLDivElement>(null);
  const availability = useTicketAvailability(communityId, { enabled: open });
  const isReport = ticket.stream === "moderation";
  const contact = availability.data?.[ticket.stream]?.contact ?? null;
  const evidence = availability.data?.[ticket.stream]?.evidence ?? null;
  const illegal = reason === Reason.illegal;
  // An illegal or "something else" report has to say what is wrong.
  const detailRequired = illegal || reason === Reason.other;
  const childSafety = illegal && basis === Basis.child_safety;

  useEffect(() => {
    if (sent) thanks.current?.focus();
  }, [sent]);

  const file = useFileTicket({
    onSuccess: (accepted) => {
      setSent({
        elsewhere: accepted.platform_contact
          ? t("moderation:report.platformContact", { contact: accepted.platform_contact })
          : null,
      });
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
        isReport ? "moderation:report.error" : "intake:security.error"
      );
      if (getHttpStatus(err) === 503) {
        setNowhere(message);
        return;
      }
      toast.error(message);
    },
  });
  const pending = file.isPending;

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
    if (!topic || !subject.trim() || !body.trim()) return null;
    return { stream: "security", type: topic, subject: subject.trim(), body: body.trim() };
  };
  const ready = payload();
  const send = () => {
    if (ready && !pending) file.mutate({ ticket: ready, files });
  };

  return (
    // Open until the send settles, so what is being sent is not sent twice.
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
    >
      <DialogContent
        className="flex max-h-[85dvh] flex-col"
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            send();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{isReport ? t("moderation:report.title") : t("security.title")}</DialogTitle>
          <DialogDescription>
            {isReport ? t("moderation:report.description") : t("security.description")}
          </DialogDescription>
        </DialogHeader>

        {sent ? (
          <Empty role="status" className="border-0">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Check />
              </EmptyMedia>
              <EmptyTitle ref={thanks} tabIndex={-1} className="outline-none">
                {isReport ? t("moderation:report.thanks") : t("security.thanks")}
              </EmptyTitle>
              {sent.elsewhere ? <EmptyDescription>{sent.elsewhere}</EmptyDescription> : null}
            </EmptyHeader>
            <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("common:done")}
            </Button>
          </Empty>
        ) : (
          <>
            <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1 pb-1">
              {isReport ? (
                <>
                  <Choice
                    id="ticket-reason"
                    label={t("moderation:report.reasonLabel")}
                    placeholder={t("moderation:report.reasonPlaceholder")}
                    value={reason}
                    options={REASONS}
                    labelOf={(value) => t(`moderation:reasons.${value}`)}
                    onChange={setReason}
                    disabled={pending}
                  />
                  {illegal ? (
                    <div className="space-y-1.5">
                      <Choice
                        id="ticket-basis"
                        label={t("moderation:report.basisLabel")}
                        placeholder={t("moderation:report.basisPlaceholder")}
                        value={basis}
                        options={BASES}
                        labelOf={(value) => t(`moderation:hold.bases.${value}`)}
                        onChange={(value) => {
                          setBasis(value);
                          // A child-safety report takes no files.
                          if (value === Basis.child_safety) setFiles([]);
                        }}
                        disabled={pending}
                      />
                      <p className="text-muted-foreground text-xs">
                        {childSafety
                          ? t("moderation:report.childSafetyHelp")
                          : t("moderation:report.basisHelp")}
                      </p>
                    </div>
                  ) : null}
                  <div className="space-y-1.5">
                    <Label htmlFor="ticket-detail">
                      {detailRequired
                        ? t("moderation:report.detailRequiredLabel")
                        : t("moderation:report.detailLabel")}
                    </Label>
                    <TicketComposer
                      id="ticket-detail"
                      value={body}
                      onChange={(event) => setBody(event.target.value)}
                      placeholder={
                        detailRequired
                          ? t("moderation:report.detailRequiredPlaceholder")
                          : t("moderation:report.detailPlaceholder")
                      }
                      rows={4}
                      maxLength={DETAIL_MAX}
                      policy={childSafety ? null : evidence}
                      files={files}
                      onFilesChange={setFiles}
                      // A report is usually about a person: who it was stays in view.
                      pagePicture={{ hidePeople: false, takenOf: ticket.thing ?? null }}
                      disabled={pending}
                    />
                  </div>
                </>
              ) : (
                <>
                  <Choice
                    id="ticket-topic"
                    label={t("security.topicLabel")}
                    placeholder={t("security.topicPlaceholder")}
                    value={topic}
                    options={SECURITY_TOPICS}
                    labelOf={(value) => t(`intake:security.topics.${value}`)}
                    onChange={setTopic}
                    disabled={pending}
                  />
                  <div className="space-y-1.5">
                    <Label htmlFor="ticket-subject">{t("help.subjectLabel")}</Label>
                    <Input
                      id="ticket-subject"
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      placeholder={t("help.subjectPlaceholder")}
                      maxLength={SUBJECT_MAX}
                      disabled={pending}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ticket-body">{t("security.bodyLabel")}</Label>
                    <TicketComposer
                      id="ticket-body"
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                      placeholder={t("security.bodyPlaceholder")}
                      rows={6}
                      maxLength={BODY_MAX}
                      policy={evidence}
                      files={files}
                      onFilesChange={setFiles}
                      pagePicture={{ hidePeople: true }}
                      disabled={pending}
                    />
                  </div>
                  {/* A report about this server stays here; one about the software
                      itself goes to the project. */}
                  <p className="text-muted-foreground text-xs">{t("security.softwareNote")}</p>
                </>
              )}

              {nowhere && !availability.isPending ? (
                <p className="text-destructive text-sm" role="alert">
                  {nowhere}
                </p>
              ) : null}
            </div>

            <DialogFooter
              submitLabel={isReport ? t("moderation:report.submit") : t("security.submit")}
              onSubmit={send}
              pending={pending}
              disabled={!ready}
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
