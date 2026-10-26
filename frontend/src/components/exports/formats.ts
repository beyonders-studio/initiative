import type { FileType } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportFormatOption } from "@/components/exports/ExportButton";
import { NON_EXPORTABLE_TOOLS, SIDEBAR_TOOLS } from "@/lib/tools";

// Engine formats per file type — mirrors the backend adapter's rules.
export const FILE_TYPE_FORMATS: Record<FileType, ExportFormatOption[]> = {
  native: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "docx", labelKey: "export.formatDocx" },
    // The lossless one: the file envelope, round-trippable through the
    // editor toolbar's import.
    { format: "json", labelKey: "export.formatJson" },
  ],
  whiteboard: [{ format: "json", labelKey: "export.formatJson" }],
  spreadsheet: [
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  file: [{ format: "file", labelKey: "export.formatOriginal" }],
  smart_link: [
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};

// Type-neutral labels for mixed-type selections, where a per-type label
// ("Lexical file (.lexical)") would misdescribe the other entries in the zip.
const GENERIC_FORMAT_LABELS: Record<string, string> = {
  pdf: "export.formatPdf",
  md: "export.formatMarkdown",
  docx: "export.formatDocx",
  json: "export.formatJson",
  csv: "export.formatCsv",
  xlsx: "export.formatXlsx",
  file: "export.formatOriginal",
};

/** Formats a file selection can export: the backend requires the format
 * to be valid for EVERY selected file's type, so offer the intersection.
 * A single-type selection keeps its type's own (more precise) labels; a
 * mixed selection gets generic ones. Empty when the types share nothing
 * (e.g. an upload + a text document). */
export function fileSelectionFormats(types: FileType[]): ExportFormatOption[] {
  const unique = [...new Set(types)];
  if (unique.length === 0) return [];
  if (unique.length === 1) return FILE_TYPE_FORMATS[unique[0]] ?? [];
  const formatSets = unique.map(
    (type) => new Set((FILE_TYPE_FORMATS[type] ?? []).map((f) => f.format))
  );
  const shared = [...formatSets[0]].filter((format) => formatSets.every((set) => set.has(format)));
  return shared.map((format) => ({
    format,
    labelKey: GENERIC_FORMAT_LABELS[format] ?? "export.formatJson",
  }));
}

// Per-tool export formats, keyed by the canonical Tool enum — each mirrors
// its backend adapter's format set. Files are deliberately ABSENT: their
// formats depend on the selected files' types (selectionExportFormats
// below / FILE_TYPE_FORMATS). The registry drift test holds this table to
// NON_EXPORTABLE_TOOLS's bulkExport flags.
export const TOOL_EXPORT_FORMATS: Partial<Record<Tool, ExportFormatOption[]>> = {
  [Tool.post]: [
    // The importable envelope, and only that: a notice has no report shape,
    // so the backend offers no rendered format for one either.
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.wiki]: [
    // Every page as one document, as a text document exports, then the
    // importable envelope. Always a zip: the files filed in the wiki ride
    // beside either.
    { format: "pdf", labelKey: "export.formatWikiPdf" },
    { format: "md", labelKey: "export.formatWikiMarkdown" },
    { format: "docx", labelKey: "export.formatWikiDocx" },
    { format: "json", labelKey: "export.formatWikiJson" },
  ],
  [Tool.dashboard]: [
    // The importable envelope, and only that: a dashboard is a live canvas
    // over other tools' data, so there is nothing to render it as.
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.catalog]: [
    // The importable envelope and the pictures it names, zipped together:
    // the envelope names each picture by its stored file.
    { format: "json", labelKey: "export.formatJsonWithPictures" },
  ],
  [Tool.project]: [
    // The importable JSON backup, then the task-table report formats.
    { format: "json", labelKey: "export.formatJson" },
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
  ],
  [Tool.queue]: [
    // Reports (Markdown renders a numbered turn order), then the envelope.
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.counter_group]: [
    // Table reports, then the importable envelope.
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMd" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  [Tool.calendar]: [
    // One combined file per calendar: standard iCalendar, or the importable
    // envelope carrying the calendar and its events.
    { format: "ics", labelKey: "export.formatIcs" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};

/** Formats a selection of one tool's rows can export: the tool's own, or for
 * files the ones every selected file's type shares. Null for a tool
 * with no export source. */
export function selectionExportFormats(
  tool: Tool,
  items: { file_type?: FileType }[]
): ExportFormatOption[] | null {
  if (NON_EXPORTABLE_TOOLS.has(tool)) return null;
  if (tool === Tool.file) {
    return fileSelectionFormats(items.flatMap((item) => item.file_type ?? []));
  }
  return TOOL_EXPORT_FORMATS[tool] ?? null;
}

// ---------------------------------------------------------------------------
// Aggregate (initiative / community) export wizard
// ---------------------------------------------------------------------------

/** Wizard tool order: the sidebar's order, filtered to engine-exportable
 * tools — registry-driven, so a new bulk-exportable tool appears here
 * without a hand-wired list. */
export const AGGREGATE_EXPORT_TOOLS: Tool[] = SIDEBAR_TOOLS.filter(
  (tool) => !NON_EXPORTABLE_TOOLS.has(tool)
);

/** Report-mode format choices per tool — mirrors the backend aggregate
 * adapter's ``_REPORT_FORMATS`` (adapters/backup.py). Files are absent:
 * they choose per file type (REPORT_FILE_FORMATS). */
export const REPORT_TOOL_FORMATS: Partial<Record<Tool, ExportFormatOption[]>> = {
  [Tool.project]: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
  ],
  [Tool.queue]: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMarkdown" },
  ],
  [Tool.counter_group]: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "md", labelKey: "export.formatMarkdown" },
  ],
  [Tool.calendar]: [
    { format: "ics", labelKey: "export.formatIcs" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};

/** Report-mode per-type file formats — mirrors the backend's
 * ``_FILE_REPORT_FORMATS``. Whiteboards/links/uploads ride in their
 * canonical format and offer no choice. */
export const REPORT_FILE_FORMATS: Record<"native" | "spreadsheet", ExportFormatOption[]> = {
  native: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "docx", labelKey: "export.formatDocx" },
  ],
  spreadsheet: [
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
  ],
};
