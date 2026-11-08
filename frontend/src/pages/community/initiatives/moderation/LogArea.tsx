import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModerationActionRead } from "@/api/generated/initiativeAPI.schemas";
import { MentionText } from "@/components/user/MentionText";
import { useModerationLog, useRestoreRemoval } from "@/hooks/useModeration";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { formatDateTime } from "@/ui/lib/formatDate";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { PaginationBar } from "@/ui/pagination-bar";
import { StatusMessage } from "@/ui/status-message";

/**
 * What this initiative's moderators have done, newest first.
 *
 * The log is the only place the words a removal took down are kept, so this
 * is where a removal is read back and put back. Read through the log's own
 * row policy: it admits the initiative's moderators and nobody else.
 */
export const LogArea = ({
  communityId,
  initiativeId,
}: {
  communityId: number;
  initiativeId: number;
}) => {
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
