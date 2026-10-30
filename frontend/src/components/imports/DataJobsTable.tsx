import { Download, FileText, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { getListDataJobsQueryKey, useListDataJobs } from "@/api/generated/data-jobs/data-jobs";
import { useCancelImportJob } from "@/api/generated/imports/imports";
import type { DataJobRead } from "@/api/generated/initiativeAPI.schemas";
import { ImportReport } from "@/components/imports/ImportReport";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RelativeTime } from "@/components/ui/relative-time";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { getErrorMessage } from "@/lib/errorMessage";
import { downloadExportArtifact } from "@/lib/exportDownload";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";

const ACTIVE = new Set(["staged", "fetching", "queued", "running"]);
const POLL_MS = 5000;

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  done: "default",
  staged: "secondary",
  fetching: "secondary",
  queued: "secondary",
  running: "secondary",
  failed: "destructive",
  cancelled: "outline",
  expired: "outline",
};

/** Effective status at render time for export rows: polling stops once every
 * job is terminal, so a tab left open can hold a stale "done" row whose
 * artifact has since expired. Clamp it client-side. */
function displayStatus(job: DataJobRead): string {
  if (
    job.direction === "export" &&
    job.status === "done" &&
    job.expires_at != null &&
    new Date(job.expires_at).getTime() <= Date.now()
  ) {
    return "expired";
  }
  return job.status;
}

/** One table for both directions of the Data tab: export and import jobs
 * newest-first in one list (RLS scopes rows — members their own, community
 * admins everyone's). Per-row actions stay direction-specific: Download for
 * finished exports, Cancel for staged/queued imports, a report view for
 * terminal imports. Polls while any job of either direction is active. */
export function DataJobsTable() {
  const { t } = useTranslation(["imports", "exports"]);
  const communityId = useActiveCommunityId();
  const [reportJob, setReportJob] = useState<DataJobRead | null>(null);

  const jobsQuery = useListDataJobs(communityId, {
    query: {
      refetchInterval: (query) =>
        (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? POLL_MS : false,
    },
  });
  const cancelMutation = useCancelImportJob();
  const jobs = jobsQuery.data ?? [];

  if (jobsQuery.isLoading) {
    return (
      <SkeletonRegion>
        <TableSkeleton rows={3} columns={5} toolbar={false} />
      </SkeletonRegion>
    );
  }
  if (jobsQuery.isError) {
    return <p className="py-4 text-destructive text-sm">{t("exports:table.loadFailed")}</p>;
  }
  if (jobs.length === 0) {
    return <p className="py-4 text-muted-foreground text-sm">{t("exports:table.empty")}</p>;
  }

  const handleCancel = async (job: DataJobRead) => {
    try {
      await cancelMutation.mutateAsync({ communityId: communityId, jobId: job.id });
    } catch (err) {
      // Most often a 409: the job started running between render and click.
      // Surface it instead of the row silently flipping to "running".
      toast.error(getErrorMessage(err, "imports:job.failed"));
    } finally {
      void queryClient.invalidateQueries({
        queryKey: getListDataJobsQueryKey(communityId),
      });
    }
  };

  const rowLabel = (job: DataJobRead): string =>
    t(`${job.direction === "export" ? "exports" : "imports"}:table.source.${job.source}` as never, {
      defaultValue: job.source,
    });

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("exports:table.columns.export")}</TableHead>
            <TableHead>{t("exports:table.columns.status")}</TableHead>
            <TableHead className="hidden sm:table-cell">
              {t("exports:table.columns.created")}
            </TableHead>
            <TableHead className="text-right">
              <span className="sr-only">{t("exports:table.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => {
            const status = displayStatus(job);
            return (
              <TableRow key={job.id}>
                <TableCell className="font-medium">
                  <Badge variant="outline" className="mr-2">
                    {t(`imports:table.direction.${job.direction}`)}
                  </Badge>
                  {rowLabel(job)}
                  {job.direction === "export" && (
                    <span className="ml-1 text-muted-foreground text-xs uppercase">
                      {job.format}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[status] ?? "secondary"}>
                    {job.direction === "export"
                      ? t(`exports:table.status.${status}` as never, { defaultValue: status })
                      : t(`imports:table.status.${status}` as never, { defaultValue: status })}
                  </Badge>
                </TableCell>
                <TableCell className="hidden text-muted-foreground text-sm sm:table-cell">
                  <RelativeTime date={job.created_at} />
                </TableCell>
                <TableCell className="text-right">
                  {job.direction === "export" && status === "done" && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={t("exports:table.download")}
                      onClick={() =>
                        void downloadExportArtifact(
                          communityId,
                          job.id,
                          t as (key: string, options?: Record<string, unknown>) => string,
                          job.source,
                          job.format
                        )
                      }
                    >
                      <Download className="h-4 w-4" />
                      <span className="hidden sm:inline">{t("exports:table.download")}</span>
                    </Button>
                  )}
                  {job.direction === "import" && ACTIVE.has(job.status) && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={job.status === "running"}
                      aria-label={t("imports:table.cancel")}
                      onClick={() => void handleCancel(job)}
                    >
                      <X className="h-4 w-4" />
                      <span className="hidden sm:inline">{t("imports:table.cancel")}</span>
                    </Button>
                  )}
                  {job.direction === "import" &&
                    (job.status === "done" || job.status === "failed") && (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={t("imports:table.viewReport")}
                        onClick={() => setReportJob(job)}
                      >
                        <FileText className="h-4 w-4" />
                        <span className="hidden sm:inline">{t("imports:table.viewReport")}</span>
                      </Button>
                    )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Dialog open={reportJob != null} onOpenChange={(open) => !open && setReportJob(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("imports:table.reportTitle")}</DialogTitle>
          </DialogHeader>
          {reportJob && <ImportReport job={reportJob} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
