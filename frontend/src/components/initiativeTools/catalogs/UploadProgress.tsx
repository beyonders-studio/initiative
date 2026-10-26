import { CheckCircle2, Loader2, X, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { UploadJob } from "@/hooks/useImageUploader";

interface UploadProgressProps {
  jobs: UploadJob[];
  total: number;
  done: number;
  failed: UploadJob[];
  active: boolean;
  onDismiss: () => void;
}

/**
 * What a drop is doing.
 *
 * One strip above the wall: a bar while pictures go up, a line per file that
 * did not, and a dismiss once it is over. It says nothing about the ones that
 * worked beyond counting them — they are on the wall.
 */
export const UploadProgress = ({
  jobs,
  total,
  done,
  failed,
  active,
  onDismiss,
}: UploadProgressProps) => {
  const { t } = useTranslation("catalogs");
  if (jobs.length === 0) return null;
  const settled = done + failed.length;

  return (
    <div className="space-y-2 rounded-lg border bg-card p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {active ? (
            <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
          ) : failed.length > 0 ? (
            <XCircle className="size-4 shrink-0 text-destructive" aria-hidden />
          ) : (
            <CheckCircle2 className="size-4 shrink-0 text-primary" aria-hidden />
          )}
          <span className="truncate">
            {active
              ? t("upload.progress", { done: settled, total })
              : failed.length > 0
                ? t("upload.finishedWithFailures", { done, failed: failed.length })
                : t("upload.finished", { count: done })}
          </span>
        </div>
        {!active && (
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={t("upload.dismiss")}
            onClick={onDismiss}
          >
            <X className="size-4" />
          </Button>
        )}
      </div>
      {active && <Progress value={total > 0 ? (settled / total) * 100 : 0} />}
      {failed.length > 0 && (
        <ul className="space-y-1 text-muted-foreground text-xs">
          {failed.map((job) => (
            <li key={job.id} className="truncate">
              <span className="text-foreground">{job.file.name}</span>
              {" — "}
              {job.refusal === "type"
                ? t("upload.refusedType")
                : job.refusal === "size"
                  ? t("upload.refusedSize")
                  : job.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
