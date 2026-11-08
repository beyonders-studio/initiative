import type { ExportTasksParams } from "@/api/generated/initiativeAPI.schemas";
import { ExportButton, type ExportFormatOption } from "@/components/exports/ExportButton";

export type ExportParams = Pick<
  ExportTasksParams,
  | "conditions"
  | "sorting"
  | "tz"
  | "include_archived"
  | "group_by"
  | "bucket"
  | "hidden_groups"
  | "columns"
  | "detail"
>;

interface ExportTasksButtonProps {
  /** The selector for the snapshot — the current list filters, or an
   * ``id in_`` condition for an explicit selection. */
  params: ExportParams;
  /** Idle-state label override (e.g. "Export Selected"). */
  label?: string;
  /** See ExportButton: exactly one instance per view adopts pending jobs. */
  resumePending?: boolean;
}

const TASK_FORMATS: ExportFormatOption[] = [
  { format: "pdf", labelKey: "export.formatPdf" },
  // One task per page with description, checklist and comments (PDF only).
  { format: "pdf", labelKey: "export.formatPdfDetailed", extraParams: { layout: "detailed" } },
  { format: "csv", labelKey: "export.formatCsv" },
  { format: "xlsx", labelKey: "export.formatXlsx" },
  { format: "md", labelKey: "export.formatMd" },
  { format: "md", labelKey: "export.formatMdChecklist", extraParams: { layout: "checklist" } },
];

export function ExportTasksButton({ params, label, resumePending }: ExportTasksButtonProps) {
  return (
    <ExportButton
      endpoint="/exports/tasks"
      params={params}
      formats={TASK_FORMATS}
      filenameStem="tasks"
      label={label}
      resumePending={resumePending}
    />
  );
}
