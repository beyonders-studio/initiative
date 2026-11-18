import type { FileType } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportFormatOption } from "@/components/exports/ExportButton";
import { NON_EXPORTABLE_TOOLS, SIDEBAR_TOOLS, TOOLS, toolExportFormats } from "@/lib/tools";
import { type EditorFileType, isStoredFileType } from "@/ui/lib/fileTypes";

// Engine formats per editor file type — mirrors the backend adapter's rules.
const EDITOR_FILE_FORMATS: Record<EditorFileType, ExportFormatOption[]> = {
  lexical: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "docx", labelKey: "export.formatDocx" },
    // The lossless one: the file envelope, round-trippable through the
    // editor toolbar's import.
    { format: "json", labelKey: "export.formatJson" },
  ],
  excalidraw: [{ format: "json", labelKey: "export.formatJson" }],
  sheet: [
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
    { format: "json", labelKey: "export.formatJson" },
  ],
  url: [
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "json", labelKey: "export.formatJson" },
  ],
};

const STORED_FILE_FORMATS: ExportFormatOption[] = [
  { format: "file", labelKey: "export.formatOriginal" },
];

/** What a file of this type exports as: the editor's formats for its own
 *  types, the stored file itself for the rest. */
export const fileTypeFormats = (type: FileType): ExportFormatOption[] =>
  isStoredFileType(type) ? STORED_FILE_FORMATS : EDITOR_FILE_FORMATS[type];

// Type-neutral labels for mixed-type selections, where a per-type label
// ("Lexical file (.lexical)") would misdescribe the other entries in the zip.
const GENERIC_FORMAT_LABELS: Record<string, string> = {
  pdf: "export.formatPdf",
  md: "export.formatMarkdown",
  docx: "export.formatDocx",
  json: "export.formatJson",
  csv: "export.formatCsv",
  xlsx: "export.formatXlsx",
  ics: "export.formatIcs",
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
  if (unique.length === 1) return fileTypeFormats(unique[0]);
  const formatSets = unique.map((type) => new Set(fileTypeFormats(type).map((f) => f.format)));
  const shared = [...formatSets[0]].filter((format) => formatSets.every((set) => set.has(format)));
  return shared.map((format) => ({
    format,
    labelKey: GENERIC_FORMAT_LABELS[format] ?? "export.formatJson",
  }));
}

// What a tool calls a format where the generic label would misdescribe it.
const TOOL_FORMAT_LABELS: Partial<Record<Tool, Record<string, string>>> = {
  // Always a zip: the files filed in the wiki ride beside every format.
  [Tool.wiki]: {
    pdf: "export.formatWikiPdf",
    md: "export.formatWikiMarkdown",
    docx: "export.formatWikiDocx",
    json: "export.formatWikiJson",
  },
  // One markdown table of the counters.
  [Tool.counter_group]: { md: "export.formatMd" },
};

// Per-tool export formats, in the order the tool's record offers them. Files
// are deliberately ABSENT: their formats depend on the selected files' types
// (selectionExportFormats below / fileTypeFormats).
export const TOOL_EXPORT_FORMATS: Partial<Record<Tool, ExportFormatOption[]>> = Object.fromEntries(
  TOOLS.flatMap((tool) => {
    const formats = toolExportFormats(tool);
    if (!formats?.length) return [];
    const options = formats.map((format) => ({
      format,
      labelKey: TOOL_FORMAT_LABELS[tool]?.[format] ?? GENERIC_FORMAT_LABELS[format],
    }));
    return [[tool, options]];
  })
);

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
  // One spreadsheet of each initiative's contacts.
  [Tool.contact]: [{ format: "csv", labelKey: "export.formatCsv" }],
};

/** Report-mode per-type file formats — mirrors the backend's
 * ``_FILE_REPORT_FORMATS``. Whiteboards/links/uploads ride in their
 * canonical format and offer no choice. */
export const REPORT_FILE_FORMATS: Record<"lexical" | "sheet", ExportFormatOption[]> = {
  lexical: [
    { format: "pdf", labelKey: "export.formatPdf" },
    { format: "md", labelKey: "export.formatMarkdown" },
    { format: "docx", labelKey: "export.formatDocx" },
  ],
  sheet: [
    { format: "csv", labelKey: "export.formatCsv" },
    { format: "xlsx", labelKey: "export.formatXlsx" },
  ],
};
