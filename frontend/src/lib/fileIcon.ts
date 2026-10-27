/**
 * The mark a file draws when it has no picture of its own.
 *
 * A file is not one sort of thing: a spreadsheet, a whiteboard, a PDF and a
 * link to Figma are all files, and drawing them all as a scroll says nothing
 * about which is which. The rule was written into the file card; it is here
 * so the relations card can obey the same one rather than a copy of it that
 * drifts.
 */

import {
  FileArchive,
  FileAudio,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileVideo,
  ImageIcon,
  PenTool,
  Presentation,
  ScrollText,
  Sheet,
} from "lucide-react";
import type { ComponentType } from "react";

import { FileKind, FileType } from "@/api/generated/initiativeAPI.schemas";
import { FILE_TYPE_KINDS } from "@/lib/fileTypes";
import { getFileTypeLabel } from "@/lib/fileUtils";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";

/** The facts that decide the mark. Every surface carrying a file has these,
 *  under these names — a summary, a recent item, a link's far end. The media
 *  type and filename stand in for the type of a file not yet uploaded. */
export interface FileFacets {
  file_type?: string | null;
  mime_type?: string | null;
  original_filename?: string | null;
  smart_link_url?: string | null;
}

/** Both a Lucide icon and a provider's brand mark satisfy this. */
export type FileMark = ComponentType<{ className?: string }>;

interface Mark {
  Icon: FileMark;
  colorClass: string;
}

const PLAIN: Mark = { Icon: ScrollText, colorClass: "text-muted-foreground" };
const GENERIC: Mark = { Icon: FileText, colorClass: "text-muted-foreground" };

/** Each kind's mark. A kind left out draws the generic file. */
const KIND_MARKS: Partial<Record<FileKind, Mark>> = {
  [FileKind.document]: { Icon: FileText, colorClass: "text-blue-600" },
  [FileKind.spreadsheet]: { Icon: FileSpreadsheet, colorClass: "text-green-600" },
  [FileKind.presentation]: { Icon: Presentation, colorClass: "text-orange-500" },
  [FileKind.whiteboard]: { Icon: PenTool, colorClass: "text-purple-500" },
  [FileKind.pdf]: { Icon: FileText, colorClass: "text-red-500" },
  [FileKind.image]: { Icon: ImageIcon, colorClass: "text-emerald-500" },
  [FileKind.video]: { Icon: FileVideo, colorClass: "text-rose-500" },
  [FileKind.audio]: { Icon: FileAudio, colorClass: "text-sky-500" },
  [FileKind.archive]: { Icon: FileArchive, colorClass: "text-amber-600" },
  [FileKind.text]: { Icon: FileText, colorClass: "text-gray-500" },
  [FileKind.link]: PLAIN,
};

/** The types drawn apart from the rest of their kind. */
const TYPE_MARKS: Partial<Record<FileType, Mark>> = {
  [FileType.lexical]: PLAIN,
  [FileType.sheet]: { Icon: Sheet, colorClass: "text-emerald-500" },
  [FileType.md]: { Icon: FileCode, colorClass: "text-indigo-500" },
  [FileType.html]: { Icon: FileText, colorClass: "text-purple-500" },
};

/** The type a file not yet uploaded will be drawn as, by its format's label. */
const LABEL_TYPES: Record<string, FileType> = {
  PDF: FileType.pdf,
  Word: FileType.docx,
  Excel: FileType.xlsx,
  PowerPoint: FileType.pptx,
  Text: FileType.txt,
  HTML: FileType.html,
  Image: FileType.png,
  Markdown: FileType.md,
  File: FileType.other,
};

const typeOf = (facets: FileFacets): FileType | undefined => {
  if (facets.file_type) {
    return Object.hasOwn(FILE_TYPE_KINDS, facets.file_type)
      ? (facets.file_type as FileType)
      : undefined;
  }
  if (facets.mime_type || facets.original_filename) {
    return LABEL_TYPES[getFileTypeLabel(facets.mime_type, facets.original_filename)];
  }
  return undefined;
};

/**
 * The icon and its colour class.
 *
 * A smart link whose URL is recognised shows that provider's brand mark; the
 * registry falls back to a generic link for a URL it does not know.
 */
export const fileIcon = (facets: FileFacets): Mark => {
  const type = typeOf(facets);
  const provider =
    type === FileType.url && facets.smart_link_url
      ? matchSmartLinkProvider(facets.smart_link_url)
      : null;
  if (provider) {
    return { Icon: provider.icon, colorClass: "text-muted-foreground" };
  }
  if (!type) return PLAIN;
  return TYPE_MARKS[type] ?? KIND_MARKS[FILE_TYPE_KINDS[type]] ?? GENERIC;
};
