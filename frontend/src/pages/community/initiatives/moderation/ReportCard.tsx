import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModerationReportRead, RemovalReason } from "@/api/generated/initiativeAPI.schemas";
import { ReportOutcome as Outcome } from "@/api/generated/initiativeAPI.schemas";
import { RemovalDialog } from "@/components/moderation/RemovalDialog";
import { WarnDialog } from "@/components/moderation/WarnDialog";
import { communityEvidenceUrl, EvidenceList } from "@/components/tickets/Evidence";
import { MentionText } from "@/components/user/MentionText";
import { refreshAfterHolding } from "@/hooks/useHolds";
import { useSettleReport } from "@/hooks/useModeration";
import { communityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { searchHitPath } from "@/lib/searchResults";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { formatDateTime } from "@/ui/lib/formatDate";
import { Textarea } from "@/ui/textarea";

import { SendToPlatformDialog } from "./SendToPlatformDialog";

interface ReportCardProps {
  report: ModerationReportRead;
  communityId: number;
  initiativeId: number;
}

export const ReportCard = ({ report, communityId, initiativeId }: ReportCardProps) => {
  const { t } = useTranslation("moderation");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [warning, setWarning] = useState(false);

  const settle = useSettleReport(communityId, initiativeId, {
    onSuccess: () => toast.success(t("settledToast")),
  });

  // Bound once: the schema makes it optional as well as nullable, and the
  // rendered key has to know it is neither.
  const settledAs = report.outcome ?? null;
  const open = settledAs === null;

  const label = t(`targets.${report.target_type}`, {
    defaultValue: report.target_type,
  });
  // Built the way a search result's is, from what the server says the report
  // opens — which for a comment is the thing it was said on, since a comment
  // has no page of its own. `null` once the target is gone or out of this
  // reader's reach, and then there is nothing to link.
  const targetPath = report.target_link
    ? searchHitPath({ ...report.target_link, initiative_id: report.initiative_id })
    : null;
  const gp = (path: string) => (communityId ? communityPath(communityId, path) : path);

  return (
    <Card role="region" aria-labelledby={`report-${report.id}`}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle id={`report-${report.id}`}>
              {targetPath ? (
                <Link to={gp(targetPath)} className="underline-offset-4 hover:underline">
                  {label}
                </Link>
              ) : (
                label
              )}
            </CardTitle>
            <CardDescription>
              {t("reportedCount", { count: report.reporter_count })} ·{" "}
              {t(`reasons.${report.reason}`)}
              {report.legal_basis ? ` (${t(`hold.bases.${report.legal_basis}`)})` : null} ·{" "}
              {formatDateTime(report.reported_at)}
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            {/* An illegal report went to whoever runs the server as well. */}
            {report.platform_notified_at ? (
              <Badge variant="outline">{t("platformNotified")}</Badge>
            ) : null}
            {settledAs === null ? null : (
              <Badge variant="secondary">{t(`outcomes.${settledAs}`)}</Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* What was actually reported, before what anyone said about it — a
            decision starts with reading the thing, and a card that names only
            its kind makes a moderator open every one of them to find out. */}
        {report.target_excerpt ? (
          <blockquote className="whitespace-pre-wrap break-words border-l-2 py-1 pl-3 text-sm">
            <MentionText text={report.target_excerpt} />
          </blockquote>
        ) : (
          // Deleted since, or beyond this reader's reach — the two are one
          // answer here, and the report still stands either way.
          <p className="text-muted-foreground text-sm italic">{t("targetUnavailable")}</p>
        )}

        {report.details.length > 0 && (
          <div className="space-y-2">
            {/* Unattributed on purpose: the count is what a decision rests on,
                and reporting stays confidential inside the community. */}
            <p className="font-medium text-sm">{t("whatTheySaid")}</p>
            {report.details.map((detail, i) => (
              // A real key would mean serving a per-reporter id, which is the
              // one thing this payload withholds; the list is read-only and
              // append-only, so the index is stable.
              // biome-ignore lint/suspicious/noArrayIndexKey: no id is served here
              <p key={`${report.id}-${i}`} className="rounded-md bg-muted px-3 py-2 text-sm">
                {detail}
              </p>
            ))}
          </div>
        )}

        {(report.evidence ?? []).length > 0 && (
          <div className="space-y-2">
            {/* As unattributed as the words: the reporters' files, together. */}
            <p className="font-medium text-sm">{t("attached")}</p>
            <EvidenceList
              items={report.evidence ?? []}
              urlFor={(id) => communityEvidenceUrl(communityId, id)}
              blurred
            />
          </div>
        )}

        {open ? (
          <div className="space-y-3 border-t pt-4">
            {/* Review the thing where it lives — this page decides, it does not
                act on content. */}
            <p className="text-muted-foreground text-sm">{t("reviewElsewhere")}</p>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("notePlaceholder")}
              rows={2}
            />
            {report.reason === "illegal" && (
              <p className="font-medium text-sm">{t("suggestHold")}</p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={settle.isPending}
                onClick={() =>
                  settle.mutate({
                    reportId: report.id,
                    body: { outcome: Outcome.dismissed, note: note.trim() || null },
                  })
                }
              >
                {t("actions.dismiss")}
              </Button>
              {/* Each acts on the reported thing: taking it down, or telling
                  whoever wrote it. */}
              <Button
                variant="outline"
                size="sm"
                disabled={settle.isPending}
                onClick={() => setRemoving(true)}
              >
                {t("actions.remove")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={settle.isPending}
                onClick={() => setWarning(true)}
              >
                {t("actions.warn")}
              </Button>
              {/* Not this community's to settle: whoever runs the server takes
                  it, with the content left up or hidden while they look. */}
              <Button
                variant="outline"
                size="sm"
                disabled={settle.isPending}
                onClick={() => setSending(true)}
              >
                {t("sendToPlatform.action")}
              </Button>
            </div>
            <RemovalDialog
              open={removing}
              onOpenChange={setRemoving}
              targetType={report.target_type}
              initialReason={report.reason as RemovalReason}
              initialNote={note}
              pending={settle.isPending}
              onConfirm={(removal) =>
                settle.mutate(
                  {
                    reportId: report.id,
                    body: {
                      outcome: Outcome.content_removed,
                      note: removal.note,
                      // Only when it differs from what it was reported for.
                      removal_reason: removal.reason === report.reason ? null : removal.reason,
                    },
                  },
                  { onSuccess: () => setRemoving(false) }
                )
              }
            />
            <WarnDialog
              open={warning}
              onOpenChange={setWarning}
              pending={settle.isPending}
              onConfirm={(message) =>
                settle.mutate(
                  {
                    reportId: report.id,
                    body: { outcome: Outcome.member_warned, note: note.trim() || null, message },
                  },
                  { onSuccess: () => setWarning(false) }
                )
              }
            />
            <SendToPlatformDialog
              open={sending}
              onOpenChange={setSending}
              report={report}
              note={note}
              sending={settle.isPending}
              onSend={(body) =>
                settle.mutate(
                  { reportId: report.id, body },
                  {
                    onSuccess: () => {
                      setSending(false);
                      // What was hidden is gone from every view of it.
                      if (body.outcome === Outcome.held) void refreshAfterHolding();
                    },
                  }
                )
              }
            />
          </div>
        ) : (
          <div className="space-y-1 border-t pt-4 text-muted-foreground text-sm">
            {report.note && <p>{report.note}</p>}
            <p>
              {t("settledAt", {
                when: report.decided_at ? formatDateTime(report.decided_at) : "",
              })}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
