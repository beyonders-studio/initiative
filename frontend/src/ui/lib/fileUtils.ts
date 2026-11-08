import { FileKind, type FileSummary } from "@/api/generated/initiativeAPI.schemas";

/** What a file made from an upload is called until somebody names it. */
export function nameWithoutExtension(filename: string): string {
  return filename.replace(/\.[^/.]+$/, "") || filename;
}

/**
 * Whether a file's extension is on an `accept` list of extensions.
 *
 * A file picker filters by `accept` itself; a file dropped from the desktop
 * skips the picker, so a drop target has to ask.
 */
export function matchesAccept(filename: string, accept: string): boolean {
  const ext = getFileExtension(filename);
  if (!ext) return false;
  return accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .includes(`.${ext}`);
}

/**
 * Format bytes to a human-readable string.
 * @param bytes - Number of bytes
 * @param decimals - Number of decimal places (default: 1)
 */
export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return "0 Bytes";

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];

  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${parseFloat((bytes / k ** i).toFixed(dm))} ${sizes[i]}`;
}

/**
 * Get the file extension from a filename or URL.
 * @param filename - Filename or URL path
 * @returns Extension without the dot (e.g., "pdf")
 */
export function getFileExtension(filename: string | null | undefined): string {
  if (!filename) return "";
  const lastDot = filename.lastIndexOf(".");
  if (lastDot === -1) return "";
  return filename.substring(lastDot + 1).toLowerCase();
}

/**
 * Get a display-friendly file type label from MIME type or extension.
 */
export function getFileTypeLabel(
  mimeType: string | null | undefined,
  filename: string | null | undefined
): string {
  // Try to get extension from filename first
  const ext = getFileExtension(filename);

  const extensionLabels: Record<string, string> = {
    pdf: "PDF",
    doc: "Word",
    docx: "Word",
    xls: "Excel",
    xlsx: "Excel",
    ppt: "PowerPoint",
    pptx: "PowerPoint",
    txt: "Text",
    html: "HTML",
    htm: "HTML",
    png: "Image",
    jpg: "Image",
    jpeg: "Image",
    gif: "Image",
    webp: "Image",
    svg: "Image",
    md: "Markdown",
    markdown: "Markdown",
  };

  if (ext && extensionLabels[ext]) {
    return extensionLabels[ext];
  }

  // Fall back to MIME type
  const mimeLabels: Record<string, string> = {
    "application/pdf": "PDF",
    "application/msword": "Word",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "text/plain": "Text",
    "text/html": "HTML",
    "image/png": "Image",
    "image/jpeg": "Image",
    "image/gif": "Image",
    "image/webp": "Image",
    "image/svg+xml": "Image",
    "text/markdown": "Markdown",
  };

  if (mimeType && mimeLabels[mimeType]) {
    return mimeLabels[mimeType];
  }

  // Any other format is named by its extension: PSD, BLEND, ZIP.
  return ext ? ext.toUpperCase() : "File";
}

/**
 * The picture a file is shown by on a card or a tile: its thumbnail for a
 * picture or a video, a picture itself until its thumbnail is drawn, and any
 * other file's featured image. `null` where it has none, and its icon stands
 * in.
 */
export const filePicture = (
  file: Pick<FileSummary, "thumbnail_url" | "kind" | "file_url" | "featured_image_url">
): string | null =>
  file.thumbnail_url ?? (file.kind === FileKind.image ? file.file_url : file.featured_image_url);
