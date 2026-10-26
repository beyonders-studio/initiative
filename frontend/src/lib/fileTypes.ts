/**
 * What a file is: its type, and the kind that decides how it is shown.
 *
 * Mirrors `backend/app/core/file_types.py`. A file's type is its format: the
 * editor's own formats, kept as a body, and the formats an upload can be,
 * kept as stored versions. Its kind follows from the type.
 */

import { FileKind, FileType } from "@/api/generated/initiativeAPI.schemas";

export const FILE_TYPE_KINDS: Record<FileType, FileKind> = {
  [FileType.lexical]: FileKind.document,
  [FileType.excalidraw]: FileKind.whiteboard,
  [FileType.sheet]: FileKind.spreadsheet,
  [FileType.url]: FileKind.link,
  [FileType.pdf]: FileKind.pdf,
  [FileType.doc]: FileKind.document,
  [FileType.docx]: FileKind.document,
  [FileType.xls]: FileKind.spreadsheet,
  [FileType.xlsx]: FileKind.spreadsheet,
  [FileType.ppt]: FileKind.presentation,
  [FileType.pptx]: FileKind.presentation,
  [FileType.txt]: FileKind.text,
  [FileType.html]: FileKind.text,
  [FileType.md]: FileKind.document,
  [FileType.png]: FileKind.image,
  [FileType.jpeg]: FileKind.image,
  [FileType.gif]: FileKind.image,
  [FileType.webp]: FileKind.image,
  [FileType.svg]: FileKind.image,
  [FileType.other]: FileKind.other,
};

/** The types the editor creates and keeps as a body. */
export const EDITOR_FILE_TYPES = [
  FileType.lexical,
  FileType.excalidraw,
  FileType.sheet,
  FileType.url,
] as const;

export type EditorFileType = (typeof EDITOR_FILE_TYPES)[number];

/** Whether a file of this type is stored versions rather than a body. */
export const isStoredFileType = (type: FileType): type is Exclude<FileType, EditorFileType> =>
  !(EDITOR_FILE_TYPES as readonly FileType[]).includes(type);
