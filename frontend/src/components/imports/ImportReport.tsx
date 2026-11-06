import { useTranslation } from "react-i18next";

import type { DataJobRead, ImportRowFailure } from "@/api/generated/initiativeAPI.schemas";
import { getErrorMessage } from "@/lib/errorMessage";

interface BackupResult {
  initiatives?: Array<{ source_id: number; initiative_id: number; name: string }>;
  per_tool?: Record<string, { created: number; failed: number; skipped: number }>;
  entries?: Array<{ title: string; tool: string; status: string; error?: string | null }>;
  assets_restored?: number;
  assets_deduped?: number;
  unmatched_handles?: string[];
}

interface EnvelopeResult {
  entity_title?: string;
  created?: Record<string, number>;
  unmatched_handles?: string[];
  failed_rows?: ImportRowFailure[];
}

/** Render a terminal import job's persisted report — backup jobs get the
 * per-initiative / per-tool breakdown, envelope jobs the created counts, and
 * a spreadsheet the rows it left out. Shared by the wizard's final step and
 * the Data tab's report view; an import applied in the request reports the
 * same way, as a finished job. */
export function ImportReport({ job }: { job: Pick<DataJobRead, "status" | "error" | "result"> }) {
  const { t } = useTranslation("imports");

  if (job.status !== "done" && job.status !== "failed") {
    return null;
  }
  if (job.status === "failed") {
    return (
      <div className="space-y-1 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm">
        <p>
          {getErrorMessage({ response: { data: { detail: job.error } } }, "imports:job.failed")}
        </p>
        <p className="text-muted-foreground text-xs">{t("wizard.report.nothing")}</p>
      </div>
    );
  }

  const result = (job.result ?? {}) as BackupResult & EnvelopeResult;
  const failedEntries = (result.entries ?? []).filter((e) => e.status === "failed");

  return (
    <div className="space-y-3 text-sm">
      {result.initiatives && result.initiatives.length > 0 && (
        <p className="font-medium">
          {t("wizard.report.initiativesCreated", { count: result.initiatives.length })}
          <span className="ml-1 font-normal text-muted-foreground">
            ({result.initiatives.map((i) => i.name).join(", ")})
          </span>
        </p>
      )}
      {result.per_tool && (
        <div className="space-y-1 rounded-lg border p-3">
          {Object.entries(result.per_tool).map(([tool, counts]) => (
            <p key={tool} className="text-xs">
              <span className="font-medium">
                {t(`table.source.initiative-${tool.replaceAll("_", "-")}` as never, {
                  defaultValue: tool,
                })}
              </span>
              {" — "}
              {t("wizard.report.perTool", {
                created: counts.created,
                failed: counts.failed,
                skipped: counts.skipped,
              })}
            </p>
          ))}
        </div>
      )}
      {!result.per_tool && result.created && (
        <div className="rounded-lg border p-3 text-xs">
          {result.entity_title && <p className="font-medium">{result.entity_title}</p>}
          <p className="text-muted-foreground">
            {Object.entries(result.created)
              .filter(([, count]) => count > 0)
              .map(([noun, count]) => `${noun}: ${count}`)
              .join(" · ")}
          </p>
        </div>
      )}
      {(result.assets_restored ?? 0) + (result.assets_deduped ?? 0) > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("wizard.report.assets", {
            restored: result.assets_restored ?? 0,
            deduped: result.assets_deduped ?? 0,
          })}
        </p>
      )}
      {(result.unmatched_handles?.length ?? 0) > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("wizard.report.unmatchedHandles", {
            handles: (result.unmatched_handles ?? []).join(", "),
          })}
        </p>
      )}
      {(result.failed_rows?.length ?? 0) > 0 && (
        <div className="space-y-1">
          <p className="text-xs">
            {t("wizard.report.failedRows", { count: result.failed_rows?.length ?? 0 })}
          </p>
          <ul className="max-h-48 space-y-0.5 overflow-y-auto text-muted-foreground text-xs">
            {(result.failed_rows ?? []).map((failure) => (
              <li key={failure.row}>
                {t("wizard.report.failedRow", {
                  row: failure.row,
                  field: t(`wizard.contacts.targets.${failure.field}` as never, {
                    defaultValue: failure.field,
                  }),
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {failedEntries.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs">{t("wizard.report.failedEntries")}</p>
          <ul className="space-y-0.5 text-muted-foreground text-xs">
            {failedEntries.map((entry) => (
              <li key={`${entry.tool}-${entry.title}`}>
                {entry.title} ({entry.tool})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
