import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CollectionRead } from "@/api/generated/initiativeAPI.schemas";
import { useAppConfig } from "@/hooks/useAppConfig";
import { invalidateCollectionContents, useUploadToCollection } from "@/hooks/useCollections";
import { getErrorMessage } from "@/lib/errorMessage";

export type UploadStatus = "queued" | "uploading" | "done" | "failed";

export interface UploadJob {
  id: number;
  file: File;
  status: UploadStatus;
  /** Why it failed — the server's answer, or too big to send. */
  error?: string;
  tooLarge?: boolean;
}

/** How many files go up at once. Enough to fill a connection; few enough
 *  that a drop of a hundred does not open a hundred requests. */
const CONCURRENCY = 3;

/** How many files land between refreshes of the wall mid-drop. A drop of a
 *  hundred shows itself arriving in tens rather than all at once at the end —
 *  and rather than a hundred refetches, which is a rate limit. */
const REFRESH_EVERY = 10;

let nextId = 1;

/**
 * A queue of files on their way into a collection: each uploaded into the
 * collection's initiative, then put in the collection.
 *
 * One file at a time per slot, a few at a time, so a bad file fails on its own
 * and the rest go up. A file over the server's ceiling is refused here first,
 * in the same list, so somebody who dropped a folder sees "x.mov — too large"
 * beside the ones that worked rather than a toast per file.
 *
 * The wall is refetched every few arrivals and once when the queue drains,
 * rather than after each file: forty refetches mid-drop would reflow the wall
 * forty times.
 */
export function useCollectionUploader(
  collection: Pick<CollectionRead, "id" | "initiative_id"> | undefined
) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const { maxUploadBytes } = useAppConfig();
  const upload = useUploadToCollection(collection);
  const uploadRef = useRef(upload);
  uploadRef.current = upload;
  const running = useRef(0);

  const enqueue = useCallback(
    (files: File[]) => {
      setJobs((current) => [
        ...current,
        ...files.map(
          (file): UploadJob =>
            maxUploadBytes !== null && file.size > maxUploadBytes
              ? { id: nextId++, file, status: "failed", tooLarge: true }
              : { id: nextId++, file, status: "queued" }
        ),
      ]);
    },
    [maxUploadBytes]
  );

  // The pump: whenever there is room and something queued, start it.
  useEffect(() => {
    const queued = jobs.filter((job) => job.status === "queued");
    if (queued.length === 0 || running.current >= CONCURRENCY) return;
    const starting = queued.slice(0, CONCURRENCY - running.current);
    running.current += starting.length;
    setJobs((current) =>
      current.map((job) =>
        starting.some((s) => s.id === job.id) ? { ...job, status: "uploading" } : job
      )
    );
    for (const job of starting) {
      uploadRef.current
        .mutateAsync(job.file)
        .then(() => {
          setJobs((current) =>
            current.map((j) => (j.id === job.id ? { ...j, status: "done" } : j))
          );
        })
        .catch((error: unknown) => {
          setJobs((current) =>
            current.map((j) =>
              j.id === job.id
                ? {
                    ...j,
                    status: "failed",
                    error: getErrorMessage(error, "files:create.uploadError"),
                  }
                : j
            )
          );
        })
        .finally(() => {
          running.current -= 1;
          // Re-run the pump for whatever is still queued.
          setJobs((current) => [...current]);
        });
    }
  }, [jobs]);

  const counts = useMemo(() => {
    const total = jobs.length;
    const done = jobs.filter((j) => j.status === "done").length;
    const failed = jobs.filter((j) => j.status === "failed");
    const active = jobs.some((j) => j.status === "queued" || j.status === "uploading");
    return { total, done, failed, active };
  }, [jobs]);

  // The wall is refreshed every few arrivals and once more when the drop
  // drains — never per file.
  const wasActive = useRef(false);
  const refreshedAt = useRef(0);
  useEffect(() => {
    const refresh = () => {
      refreshedAt.current = counts.done;
      void invalidateCollectionContents();
    };
    if (counts.active) {
      wasActive.current = true;
      if (counts.done - refreshedAt.current >= REFRESH_EVERY) refresh();
    } else if (wasActive.current) {
      wasActive.current = false;
      if (counts.done !== refreshedAt.current) refresh();
      refreshedAt.current = 0;
    }
  }, [counts.active, counts.done]);

  const dismiss = useCallback(() => setJobs([]), []);

  return { jobs, enqueue, dismiss, ...counts };
}
