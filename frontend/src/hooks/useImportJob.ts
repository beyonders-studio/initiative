import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useGetDataJob } from "@/api/generated/data-jobs/data-jobs";
import type { DataJobRead } from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { toast } from "@/lib/mascotToast";
import { getItem, removeItem, setItem } from "@/lib/storage";

const POLL_MS = 2000;
const TERMINAL = new Set(["done", "failed", "cancelled", "expired"]);

// A pending job id survives the component unmounting (navigation) so a
// return to an adopting view resumes the poll and surfaces the report. A
// full page reload is covered by the worker's inbox notification instead.
const pendingKey = (communityId: number) => `imports:pending:${communityId}`;

export type ImportJobPhase = "idle" | "polling" | "done" | "failed";

export interface UseImportJobOptions {
  /** Adopt a stored pending job on mount. Exactly ONE instance per view may
   * set this — the community's pending key is shared, so a second adopter would
   * report the same job twice. */
  resumePending?: boolean;
}

/** Poll-side twin of useExportJob for imports: watch a queued/running import
 * job to its terminal state and expose the terminal row (its ``result`` is
 * the report the UI renders). Unlike exports there is no download step — the
 * outcome IS the report. Toasts fire once per terminal job so every surface
 * reports identically. */
export function useImportJob({ resumePending = false }: UseImportJobOptions = {}) {
  const { t } = useTranslation("imports");
  const communityId = useActiveCommunityId();
  const [jobId, setJobId] = useState<number | null>(() => {
    if (!resumePending || !communityId) {
      return null;
    }
    const stored = Number(getItem(pendingKey(communityId)));
    return Number.isFinite(stored) && stored > 0 ? stored : null;
  });
  // The last terminal row, until the next watch()/reset() — what lets a
  // wizard render a report screen after the poll ends.
  const [terminal, setTerminal] = useState<DataJobRead | null>(null);
  // Job ids already handled — a terminal status must fire exactly once even
  // though polling re-renders keep delivering it.
  const handledJobs = useRef(new Set<number>());

  const jobQuery = useGetDataJob(communityId, jobId ?? 0, {
    query: {
      enabled: jobId != null,
      refetchInterval: (query) => (TERMINAL.has(query.state.data?.status ?? "") ? false : POLL_MS),
    },
  });

  const job = jobQuery.data;
  useEffect(() => {
    if (!jobId || !job || job.id !== jobId || !TERMINAL.has(job.status)) {
      return;
    }
    if (handledJobs.current.has(jobId)) {
      return;
    }
    handledJobs.current.add(jobId);
    setJobId(null);
    removeItem(pendingKey(communityId));
    setTerminal(job);
    if (job.status === "done") {
      toast.success(t("job.succeeded"));
    } else {
      toast.error(t("job.failed"));
    }
  }, [job, jobId, communityId, t]);

  /** Start polling a queued job (from a 202 response). */
  const watch = (id: number) => {
    setTerminal(null);
    handledJobs.current.delete(id);
    setJobId(id);
    setItem(pendingKey(communityId), String(id));
  };

  const reset = () => {
    setTerminal(null);
  };

  const phase: ImportJobPhase =
    jobId != null
      ? "polling"
      : terminal == null
        ? "idle"
        : terminal.status === "done"
          ? "done"
          : "failed";

  return {
    /** True while a job is being polled. */
    busy: jobId != null,
    phase,
    jobId,
    /** The live row while polling (progress display). */
    job: jobId != null ? job : null,
    /** The terminal row once the poll ends (its result is the report). */
    terminal,
    watch,
    reset,
  };
}
