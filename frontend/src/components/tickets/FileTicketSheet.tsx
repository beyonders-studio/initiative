/**
 * Filing a ticket: reporting something, or a security problem. Help requests
 * are asked from Help (`components/help/HelpPanel`), and feedback from its
 * own sheet.
 *
 * One sheet for both, opened by a Report flag or the security report. Like
 * Help and feedback it docks beside the page on a wide screen, so what is
 * being reported stays in view, and rises from the bottom on a phone. Each
 * kind brings its own fields; sending, the thanks and the fallback are shared.
 *
 * Once sent, the sheet thanks the reporter and, where the server gave one,
 * shows an address to write to as well.
 *
 * Where the server takes no reports here but gave an address, the sheet
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/ui/empty";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/ui/sheet";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

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
    };

export interface FileTicketSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticket: TicketKind;
  /** The community the reader is standing in, when they are in one; a
   *  report may come from nowhere. */
  communityId: number | null;
}

/** One of a few answers, as a row of chips. */
const Choice = <T extends string>({
  id,
  label,
  value,
  options,
  labelOf,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  value: T | "";
  options: T[];
  labelOf: (option: T) => string;
  onChange: (option: T) => void;
  disabled?: boolean;
}) => (
  <div className="grid gap-2">
    <span id={id} className="font-medium text-sm">
      {label}
    </span>
    <ToggleGroup
      type="single"
      value={value}
      // An answer is kept once chosen: choosing it again keeps it.
      onValueChange={(next) => next && onChange(next as T)}
      aria-labelledby={id}
      variant="outline"
      size="sm"
      className="flex-wrap justify-start"
      disabled={disabled}
    >
      {options.map((option) => (
        <ToggleGroupItem key={option} value={option} className="rounded-full px-3">
          {labelOf(option)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  </div>
);

export const FileTicketSheet = ({
  open,
  onOpenChange,
  ticket,
  communityId,
}: FileTicketSheetProps) => {
  const { t } = useTranslation(["intake", "moderation", "common"]);
  const wide = atLeast(useWidthClass(), "sm");
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
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
      modal={!wide}
    >
      <SheetContent
        side={wide ? "bottom-right" : "bottom"}
        className={cn("flex flex-col gap-0 p-0", !wide && "max-h-[85dvh] rounded-t-2xl")}
        style={wide ? undefined : { paddingBottom: "var(--safe-area-inset-bottom)" }}
        // Docked beside the page, it stays open while the page is used.
        onInteractOutside={wide ? (event) => event.preventDefault() : undefined}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            send();
          }
        }}
      >
        <SheetHeader className="space-y-1 py-4 pr-12 pl-4 text-left">
          <SheetTitle className="text-base">
            {isReport ? t("moderation:report.title") : t("security.title")}
          </SheetTitle>
          <SheetDescription>
            {isReport ? t("moderation:report.description") : t("security.description")}
          </SheetDescription>
        </SheetHeader>

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
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-4">
              {isReport ? (
                <>
                  <Choice
                    id="ticket-reason"
                    label={t("moderation:report.reasonLabel")}
                    value={reason}
                    options={REASONS}
                    labelOf={(value) => t(`moderation:reasons.${value}`)}
                    onChange={setReason}
                    disabled={pending}
                  />
                  {illegal ? (
                    <div className="grid gap-2">
                      <Choice
                        id="ticket-basis"
                        label={t("moderation:report.basisLabel")}
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
                      pagePicture={{ hidePeople: false }}
                      disabled={pending}
                    />
                  </div>
                </>
              ) : (
                <>
                  <Choice
                    id="ticket-topic"
                    label={t("security.topicLabel")}
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

            <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
              <Button
                variant="ghost"
                size="sm"
                disabled={pending}
                onClick={() => onOpenChange(false)}
              >
                {t("common:cancel")}
              </Button>
              <Button size="sm" disabled={!ready || pending} onClick={send}>
                {isReport ? t("moderation:report.submit") : t("security.submit")}
              </Button>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
};
