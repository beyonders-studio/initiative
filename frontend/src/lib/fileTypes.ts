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
  [FileType.odt]: FileKind.document,
  [FileType.rtf]: FileKind.document,
  [FileType.md]: FileKind.document,
  [FileType.xls]: FileKind.spreadsheet,
  [FileType.xlsx]: FileKind.spreadsheet,
  [FileType.ods]: FileKind.spreadsheet,
  [FileType.csv]: FileKind.spreadsheet,
  [FileType.tsv]: FileKind.spreadsheet,
  [FileType.ppt]: FileKind.presentation,
  [FileType.pptx]: FileKind.presentation,
  [FileType.odp]: FileKind.presentation,
  [FileType.png]: FileKind.image,
  [FileType.jpeg]: FileKind.image,
  [FileType.gif]: FileKind.image,
  [FileType.webp]: FileKind.image,
  [FileType.svg]: FileKind.image,
  [FileType.heic]: FileKind.image,
  [FileType.tiff]: FileKind.image,
  [FileType.mp4]: FileKind.video,
  [FileType.webm]: FileKind.video,
  [FileType.mov]: FileKind.video,
  [FileType.mp3]: FileKind.audio,
  [FileType.m4a]: FileKind.audio,
  [FileType.wav]: FileKind.audio,
  [FileType.ogg]: FileKind.audio,
  [FileType.flac]: FileKind.audio,
  [FileType.txt]: FileKind.text,
  [FileType.json]: FileKind.text,
  [FileType.html]: FileKind.text,
  [FileType.zip]: FileKind.archive,
  [FileType.tar]: FileKind.archive,
  [FileType.gz]: FileKind.archive,
  [FileType["7z"]]: FileKind.archive,
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
