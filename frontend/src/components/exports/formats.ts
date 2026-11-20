import type { FileType } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import type { ExportFormatOption } from "@/components/exports/ExportButton";
import {
  FILE_TYPE_REPORT_FORMATS,
  fileTypeExportFormats,
  NON_EXPORTABLE_TOOLS,
  SIDEBAR_TOOLS,
  TOOLS,
  toolExportFormats,
  toolReportFormats,
} from "@/lib/tools";

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

/** What a file of this type exports as: the editor's formats for its own
 *  types, the stored file itself for the rest (the backend's rule, from the
 *  records). */
export function fileTypeFormats(type: FileType): ExportFormatOption[] {
  return fileTypeExportFormats(type).map((format) => ({
    format,
    labelKey: GENERIC_FORMAT_LABELS[format],
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

/** Formats a selection of one built-in tool's rows can export: the tool's
 * own, or for files the ones every selected file's type shares. Null for a
 * tool with no export source. A tool plug-in's are its read's
 * (`genericFormatOptions`). */
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

/** Formats labelled as anything but a built-in tool's own export is: a
 *  report's choices, and a tool plug-in's. */
export const genericFormatOptions = (formats: readonly string[]): ExportFormatOption[] =>
  formats.map((format) => ({ format, labelKey: GENERIC_FORMAT_LABELS[format] }));

/** Report-mode format choices per tool, from the tool's record. Files are
 * absent: they choose per file type (REPORT_FILE_FORMATS). */
export const REPORT_TOOL_FORMATS: Partial<Record<Tool, ExportFormatOption[]>> = Object.fromEntries(
  TOOLS.flatMap((tool) => {
    const formats = toolReportFormats(tool);
    return formats.length ? [[tool, genericFormatOptions(formats)]] : [];
  })
);

/** Report-mode per-type file formats, from the files record. Whiteboards,
 * links and uploads ride in their canonical format and offer no choice. */
export const REPORT_FILE_FORMATS = Object.fromEntries(
  Object.entries(FILE_TYPE_REPORT_FORMATS).map(([type, formats]) => [
    type,
    genericFormatOptions(formats),
  ])
) as Record<keyof typeof FILE_TYPE_REPORT_FORMATS, ExportFormatOption[]>;
