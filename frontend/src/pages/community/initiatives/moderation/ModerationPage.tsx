/**
 * A community's moderation: what was reported, and what was done about it.
 *
 * Not a board. Each report is one thing to look at and decide, so the page is
 * a list with the outcomes as the actions — there is no status to drag between
 * and nothing to assign. Settled reports stay, on their own tab, because "what
 * did we do about this" is the question the row exists to answer.
 *
 * Who may see any of it is the database's decision: the tables admit the
 * people who already reach every item in the initiative, plus community admins. A
 * reader who is not one of them gets an empty list, which is the same answer
 * they get for any content they are not in.
 */

import { Link, useParams } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ModerationActionRead,
  ModerationReportRead,
  RemovalReason,
} from "@/api/generated/initiativeAPI.schemas";
import { ReportOutcome as Outcome } from "@/api/generated/initiativeAPI.schemas";
import { RemovalDialog } from "@/components/moderation/RemovalDialog";
import { WarnDialog } from "@/components/moderation/WarnDialog";
import { communityEvidenceUrl, EvidenceList } from "@/components/tickets/Evidence";
import { MentionText } from "@/components/user/MentionText";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { refreshAfterHolding } from "@/hooks/useHolds";
import { useInitiativeRoster } from "@/hooks/useInitiatives";
import {
  useInitiativeSharing,
  useModerationLog,
  useModerationReports,
  useRestoreRemoval,
  useSettleReport,
} from "@/hooks/useModeration";
import { communityPath } from "@/lib/communityUrl";
import { entityRefTypeFor, isSearchEntityType } from "@/lib/entityResolver";
import { toast } from "@/lib/mascotToast";
import { searchHitPath } from "@/lib/searchResults";
import { getUserDisplayName } from "@/lib/userDisplay";
import { SendToPlatformDialog } from "@/pages/community/initiatives/moderation/SendToPlatformDialog";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { formatDateTime } from "@/ui/lib/formatDate";
import { CardGridSkeleton, ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { StatusMessage } from "@/ui/status-message";
import { Tabs, TabsList, TabsTrigger } from "@/ui/tabs";
import { Textarea } from "@/ui/textarea";

export const ModerationPage = () => {
  const { t } = useTranslation(["moderation", "common"]);
  const communityId = useActiveCommunityId();
  const { initiativeId } = useParams({ strict: false }) as { initiativeId?: string };
  const initiative = Number(initiativeId);
  const [area, setArea] = useState<ConsoleArea>("reports");
  const [tab, setTab] = useState<"open" | "settled">("open");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useModerationReports(
    {
      communityId: communityId ?? 0,
      initiativeId: initiative,
      settled: tab === "settled",
      page,
    },
    { enabled: Boolean(communityId) && Number.isFinite(initiative) }
  );

  const reports = data?.items ?? [];

  const showTab = (next: "open" | "settled") => {
    setTab(next);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      {/* What a moderator acts on, and what they act with. The second two are
          views onto standing they already hold — being here grants nothing. */}
      <Tabs value={area} onValueChange={(v) => setArea(v as ConsoleArea)}>
        <TabsList>
          <TabsTrigger value="reports">{t("areas.reports")}</TabsTrigger>
          <TabsTrigger value="members">{t("areas.members")}</TabsTrigger>
          <TabsTrigger value="sharing">{t("areas.sharing")}</TabsTrigger>
          <TabsTrigger value="log">{t("areas.log")}</TabsTrigger>
        </TabsList>
      </Tabs>

      {area === "members" && <MembersArea initiativeId={initiative} />}
      {area === "log" && <LogArea communityId={communityId ?? 0} initiativeId={initiative} />}
      {area === "sharing" && (
        <SharingArea communityId={communityId ?? 0} initiativeId={initiative} />
      )}

      {area === "reports" && (
        <Tabs value={tab} onValueChange={(v) => showTab(v as "open" | "settled")}>
          <TabsList>
            <TabsTrigger value="open">{t("tabs.open")}</TabsTrigger>
            <TabsTrigger value="settled">{t("tabs.settled")}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}

      {area === "reports" &&
        (isLoading ? (
          <SkeletonRegion>
            <CardGridSkeleton count={3} className="space-y-4" />
          </SkeletonRegion>
        ) : (
          <div className="space-y-4">
            {reports.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {tab === "open" ? t("empty.open") : t("empty.settled")}
              </p>
            ) : (
              // A reported comment is shown by its opening words.
              reports.map((report) => (
                <ReportCard
                  key={report.id}
                  report={report}
                  communityId={communityId ?? 0}
                  initiativeId={initiative}
                />
              ))
            )}

            {/* The server's page, which may be earlier than the one asked
                for when reports settled in between left fewer pages. */}
            {data && (
              <PaginationBar
                className="pt-2"
                page={data.page}
                pageSize={data.page_size}
                totalCount={data.total_count}
                hasNext={data.has_next}
                onPageChange={setPage}
              />
            )}
          </div>
        ))}
    </div>
  );
};

type ConsoleArea = "reports" | "members" | "sharing" | "log";

/** How many members the roster area shows at once. */
const MEMBERS_PAGE_SIZE = 50;

interface ReportCardProps {
  report: ModerationReportRead;
  communityId: number;
  initiativeId: number;
}

const ReportCard = ({ report, communityId, initiativeId }: ReportCardProps) => {
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

/**
 * The initiative's roster, with each member's role.
 *
 * Read-only. Who is in an initiative and what they may do is the initiative's
 * own settings to change; this is here so a moderator deciding a report can see
 * who they are deciding about without leaving the page.
 */
const MembersArea = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useInitiativeRoster(initiativeId, {
    page,
    page_size: MEMBERS_PAGE_SIZE,
  });
  const members = data?.items ?? [];

  if (isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={5} avatar={false} />
      </SkeletonRegion>
    );
  }
  if (isError) {
    return <StatusMessage onRetry={refetch} />;
  }

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("members.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {members.map((member) => (
          <div
            key={member.user.id}
            className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
          >
            <span className="min-w-0 truncate text-sm">{getUserDisplayName(member.user)}</span>
            <div className="flex items-center gap-2">
              {member.override_share_restrictions && (
                <Badge variant="secondary">{t("members.fullAccess")}</Badge>
              )}
              <span className="text-muted-foreground text-sm">
                {member.role_display_name ?? t("members.noRole")}
              </span>
            </div>
          </div>
        ))}
        {data && (
          <PaginationBar
            className="pt-2"
            page={data.page}
            pageSize={data.page_size}
            totalCount={data.total_count}
            hasNext={data.has_next}
            onPageChange={setPage}
          />
        )}
      </CardContent>
    </Card>
  );
};

/**
 * Who can reach what, across the initiative.
 *
 * Read-only, and deliberately: changing sharing goes through the resource's own
 * control, which is the one editor for it and the one that is tested. What this
 * adds is the overview — how widely each thing is reached — so finding the one
 * shared too far does not mean opening all of them.
 */
const SharingArea = ({
  communityId,
  initiativeId,
}: {
  communityId: number;
  initiativeId: number;
}) => {
  const { t } = useTranslation(["moderation", "common"]);
  const { data, isLoading, isError, refetch } = useInitiativeSharing(communityId, initiativeId);
  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={5} avatar={false} />
      </SkeletonRegion>
    );
  }
  // A read that failed and a community that has shared nothing are different
  // answers; this says which one it is.
  if (isError) {
    return <StatusMessage onRetry={refetch} />;
  }

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("sharing.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("sharing.empty")}</p>
        ) : (
          items.map((item) => {
            const refType = isSearchEntityType(item.resource_type)
              ? entityRefTypeFor(item.resource_type)
              : null;
            const label = item.name || `${item.resource_type} ${item.resource_id}`;
            return (
              <div
                key={`${item.resource_type}-${item.resource_id}`}
                className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
              >
                <span className="min-w-0 truncate text-sm">
                  {refType ? (
                    <Link
                      to={communityPath(communityId, `/go/${refType}/${item.resource_id}`)}
                      className="underline-offset-4 hover:underline"
                    >
                      {label}
                    </Link>
                  ) : (
                    label
                  )}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {item.all_initiative_members && (
                    <Badge variant="secondary">{t("sharing.everyone")}</Badge>
                  )}
                  {/* Two counts, two keys: one string cannot pluralise on two
                      numbers at once. */}
                  <span className="text-muted-foreground text-sm">
                    {t("sharing.people", { count: item.user_grant_count })} ·{" "}
                    {t("sharing.roles", { count: item.role_grant_count })}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
};

/**
 * What this initiative's moderators have done, newest first.
 *
 * The log is the only place the words a removal took down are kept, so this
 * is where a removal is read back and put back. Read through the log's own
 * row policy: it admits the initiative's moderators and nobody else.
 */
const LogArea = ({ communityId, initiativeId }: { communityId: number; initiativeId: number }) => {
  const { t } = useTranslation(["moderation", "common"]);
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useModerationLog(
    { communityId, initiativeId, page },
    { enabled: Boolean(communityId) && Number.isFinite(initiativeId) }
  );
  const restore = useRestoreRemoval(communityId, {
    onSuccess: () => toast.success(t("log.restored")),
  });
  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <SkeletonRegion>
        <ListSkeleton rows={5} avatar={false} />
      </SkeletonRegion>
    );
  }
  if (isError) {
    return <StatusMessage onRetry={refetch} />;
  }

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("log.title")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("log.empty")}</p>
        ) : (
          items.map((entry) => (
            <LogEntry
              key={entry.id}
              entry={entry}
              restoring={restore.isPending}
              onRestore={() => restore.mutate(entry.id)}
            />
          ))
        )}
        {data && (
          <PaginationBar
            className="pt-2"
            page={data.page}
            pageSize={data.page_size}
            totalCount={data.total_count}
            hasNext={data.has_next}
            onPageChange={setPage}
          />
        )}
      </CardContent>
    </Card>
  );
};

const LogEntry = ({
  entry,
  restoring,
  onRestore,
}: {
  entry: ModerationActionRead;
  restoring: boolean;
  onRestore: () => void;
}) => {
  const { t } = useTranslation("moderation");
  const target = t(`targets.${entry.target_type}`, { defaultValue: entry.target_type });
  // Nobody signed it when the platform acted on a hold it ended.
  const actor = entry.actor?.name ?? (entry.hold_id != null ? t("log.platform") : t("log.someone"));

  return (
    <div className="space-y-2 border-b pb-3 last:border-b-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm">
          <span className="font-medium">{t(`log.acts.${entry.action}`)}</span> · {target}
          {entry.subject ? ` · ${t("log.whose", { name: entry.subject.name })}` : null}
        </p>
        <p className="text-muted-foreground text-xs">
          {t("log.by", { name: actor })} · {formatDateTime(entry.created_at)}
        </p>
      </div>
      {(entry.reason || entry.report_id != null || entry.hold_id != null) && (
        <p className="text-muted-foreground text-xs">
          {[
            entry.reason ? t(`removalReasons.${entry.reason}`) : null,
            entry.report_id != null ? t("log.fromReport") : null,
            entry.hold_id != null ? t("log.afterHold") : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {entry.note ? <p className="whitespace-pre-wrap text-sm">{entry.note}</p> : null}
      {entry.snapshot ? (
        <div className="space-y-1">
          <p className="font-medium text-muted-foreground text-xs">{t("log.whatItSaid")}</p>
          <blockquote className="whitespace-pre-wrap break-words border-l-2 py-1 pl-3 text-sm">
            <MentionText text={entry.snapshot} />
          </blockquote>
        </div>
      ) : null}
      {entry.restorable && (
        <Button variant="outline" size="sm" disabled={restoring} onClick={onRestore}>
          {t("log.restore")}
        </Button>
      )}
    </div>
  );
};
