import {
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  History,
  Loader2,
  Presentation,
  Trash2,
  Upload,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Document, Page, pdfjs } from "react-pdf";

import type { FileVersionRead } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/Markdown";
import { Lightbox } from "@/components/shared/Lightbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useDeleteFileVersion, useFileVersions, useUploadFileVersion } from "@/hooks/useFiles";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { formatBytes, getFileExtension, getFileTypeLabel } from "@/lib/fileUtils";
import { toast } from "@/lib/mascotToast";
import { resolveFileDownloadUrl, resolveFileVersionDownloadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Self-host the PDF.js worker as a same-origin app asset rather than loading it
// from a CDN. A cross-origin worker URL forces pdf.js to import() it from inside a
// blob worker, which the app's `script-src 'self'` CSP (pentest MED-001) blocks;
// bundling it keeps the worker same-origin (no CSP relaxation), guarantees the
// version matches pdfjs-dist, and works offline in the native app. Both URLs are
// built by the pdfjs plugin in vite.config.ts.
pdfjs.GlobalWorkerOptions.workerSrc = __PDFJS_WORKER_URL__;

// pdf.js decodes JBIG2, CCITT fax and JPEG 2000 images in WebAssembly, and only
// looks for those modules if it is told where they live. Scanned and faxed PDFs
// are where they turn up. Defined once at module scope: react-pdf reloads the
// file whenever this object's identity changes.
const PDF_OPTIONS = { wasmUrl: __PDFJS_WASM_URL__ };

interface UploadedFileViewerProps {
  fileId: number;
  /** The file's OWNING community — downloads are addressed by it, not the
   * active community, so cross-community surfaces (My Tools) resolve correctly. */
  communityId: number;
  fileUrl: string;
  contentType?: string | null;
  originalFilename?: string | null;
  fileSize?: number | null;
  /** Whether the current user can upload a new version (write or owner). */
  canEdit?: boolean;
  /** Whether the current user owns the file (can delete versions). */
  canDeleteVersions?: boolean;
}

/**
 * Live "Version N · M ago" label for one version row. A component (not an inline
 * hook) so `useRelativeTime` can run per row inside the versions map.
 */
const VersionLabel = ({ number, createdAt }: { number: number; createdAt: string }) => {
  const { t } = useTranslation(["files", "common"]);
  const relative = useRelativeTime(createdAt);
  return <>{t("versions.versionLabel", { number, date: relative })}</>;
};

export const UploadedFileViewer = ({
  fileId,
  communityId,
  fileUrl,
  contentType,
  originalFilename,
  fileSize,
  canEdit = false,
  canDeleteVersions = false,
}: UploadedFileViewerProps) => {
  const { t } = useTranslation(["files", "common"]);
  const { maxUploadBytes } = useAppConfig();

  // ── Version history ─────────────────────────────────────────────────────
  const { data: versions } = useFileVersions(fileId);
  const uploadVersion = useUploadFileVersion();
  const deleteVersion = useDeleteFileVersion();
  const versionInputRef = useRef<HTMLInputElement>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versionPendingDelete, setVersionPendingDelete] = useState<FileVersionRead | null>(null);

  const currentVersion = useMemo(() => versions?.find((v) => v.is_current) ?? null, [versions]);
  const selectedVersion = useMemo(() => {
    if (selectedVersionId == null) return currentVersion;
    return versions?.find((v) => v.id === selectedVersionId) ?? currentVersion;
  }, [versions, selectedVersionId, currentVersion]);
  const isViewingCurrent = selectedVersion == null || selectedVersion.is_current;
  const hasMultipleVersions = (versions?.length ?? 0) > 1;

  // Always render via the version-specific URL once the version is known —
  // including the current version. The version id lives in the path, so when a
  // new version is uploaded (the current version's id changes) the URL changes
  // too, busting the browser/react-pdf/<img> cache that keys on the URL string.
  // (The plain /download URL is constant and would otherwise show stale bytes.)
  // Falls back to the file download URL only until the version list loads.
  const resolvedUrl = selectedVersion
    ? resolveFileVersionDownloadUrl(fileId, selectedVersion.id, communityId)
    : resolveFileDownloadUrl(fileId, communityId);
  const inlineUrl = selectedVersion
    ? resolveFileVersionDownloadUrl(fileId, selectedVersion.id, communityId, true)
    : resolveFileDownloadUrl(fileId, communityId, true);

  // Header metadata follows the selected version (falls back to props/current).
  const displayFilename = selectedVersion?.original_filename ?? originalFilename;
  const displayFileSize = selectedVersion?.file_size ?? fileSize;

  const fileTypeLabel = getFileTypeLabel(contentType, displayFilename);
  const extension = getFileExtension(displayFilename || fileUrl);

  // PDF viewer state
  const [numPages, setNumPages] = useState<number | null>(null);
  const [scale, setScale] = useState(1.0);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [baseWidth, setBaseWidth] = useState<number | null>(null);
  // Intrinsic width (PDF units) of the widest page in the file. Every page
  // renders at one shared scale derived from it, so a file that mixes single
  // pages with spreads keeps their relative widths instead of stretching each
  // page to fill the viewer.
  const [maxPageWidth, setMaxPageWidth] = useState<number | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  // The file the measurement below belongs to, so a version switched mid-flight
  // doesn't get the previous file's scale.
  const measuredPdfRef = useRef<PDFDocumentProxy | null>(null);

  // Image viewer state
  const [lightboxOpen, setLightboxOpen] = useState(false);

  // Markdown viewer state
  const [markdownContent, setMarkdownContent] = useState<string | null>(null);
  const [showRendered, setShowRendered] = useState(true);

  // Determine file type for rendering strategy
  const isPdf = extension === "pdf" || contentType === "application/pdf";
  const isText = extension === "txt" || contentType === "text/plain";
  const isHtml = extension === "html" || extension === "htm" || contentType === "text/html";
  const isImage =
    contentType?.startsWith("image/") ||
    ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(extension);
  const isMarkdown =
    extension === "md" || extension === "markdown" || contentType === "text/markdown";
  // Played by the browser's own player; one it cannot play offers the download.
  const isVideo = contentType?.startsWith("video/") ?? false;
  const isAudio = contentType?.startsWith("audio/") ?? false;

  // Measure toolbar width once on mount for PDF sizing
  useEffect(() => {
    const measureWidth = () => {
      if (toolbarRef.current) {
        setBaseWidth(toolbarRef.current.clientWidth);
      }
    };

    // Measure after a short delay to ensure layout is complete
    const timeoutId = setTimeout(measureWidth, 50);
    return () => clearTimeout(timeoutId);
  }, []);

  // Fetch markdown content for rendering
  useEffect(() => {
    if (!isMarkdown || !inlineUrl) return;
    fetch(inlineUrl, { credentials: "include" })
      .then((res) => res.text())
      .then(setMarkdownContent)
      .catch(() => setMarkdownContent(""));
  }, [isMarkdown, inlineUrl]);

  // Office files can't be rendered in-browser without external services
  const isWord =
    ["doc", "docx"].includes(extension) ||
    contentType === "application/msword" ||
    contentType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const isExcel =
    ["xls", "xlsx"].includes(extension) ||
    contentType === "application/vnd.ms-excel" ||
    contentType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const isPowerPoint =
    ["ppt", "pptx"].includes(extension) ||
    contentType === "application/vnd.ms-powerpoint" ||
    contentType === "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  const isOffice = isWord || isExcel || isPowerPoint;

  const handleDownload = () => {
    if (!resolvedUrl) return;

    const link = document.createElement("a");
    link.href = resolvedUrl;
    link.download = displayFilename || "file";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOpenInNewTab = () => {
    if (!inlineUrl) return;
    window.open(inlineUrl, "_blank", "noopener,noreferrer");
  };

  const handleVersionFileSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (maxUploadBytes !== null && file.size > maxUploadBytes) {
      toast.error(t("create.fileTooLarge"));
      return;
    }
    uploadVersion.mutate(
      { fileId, file },
      {
        // Show the newly uploaded (now current) version.
        onSuccess: () => {
          setSelectedVersionId(null);
          setVersionsOpen(false);
        },
      }
    );
  };

  const handleSelectVersion = (version: FileVersionRead) => {
    setSelectedVersionId(version.is_current ? null : version.id);
    setVersionsOpen(false);
  };

  const handleConfirmDeleteVersion = () => {
    if (!versionPendingDelete) return;
    const deletedId = versionPendingDelete.id;
    deleteVersion.mutate(
      { fileId, versionId: deletedId },
      {
        onSuccess: () => {
          // If the version being viewed was deleted, fall back to current.
          if (selectedVersionId === deletedId) {
            setSelectedVersionId(null);
          }
          setVersionPendingDelete(null);
        },
      }
    );
  };

  const onDocumentLoadSuccess = async (pdf: PDFDocumentProxy) => {
    measuredPdfRef.current = pdf;
    setNumPages(pdf.numPages);
    setMaxPageWidth(null);
    setPdfError(null);

    // Read each page's viewport (page dictionaries only — no rendering) to find
    // the widest one. `getViewport` already accounts for page rotation.
    const widths = await Promise.all(
      Array.from({ length: pdf.numPages }, (_, index) =>
        pdf
          .getPage(index + 1)
          .then((page) => page.getViewport({ scale: 1 }).width)
          // One unreadable page shouldn't decide the scale for the rest.
          .catch(() => 0)
      )
    );

    // A newer version finished loading while we were measuring.
    if (measuredPdfRef.current !== pdf) return;

    const widest = Math.max(...widths);
    if (widest > 0) {
      setMaxPageWidth(widest);
    } else {
      setPdfError(t("viewer.pdfError"));
    }
  };

  const onDocumentLoadError = (error: Error) => {
    console.error("PDF load error:", error);
    setPdfError(t("viewer.pdfError"));
  };

  const zoomIn = () => setScale((prev) => Math.min(2.5, prev + 0.25));
  const zoomOut = () => setScale((prev) => Math.max(0.5, prev - 0.25));

  // One scale for the whole file: fit the widest page to the viewer (minus the
  // container padding), then apply the user's zoom on top. Null until the pages
  // have been measured.
  const pageScale =
    baseWidth !== null && maxPageWidth !== null ? ((baseWidth - 32) * scale) / maxPageWidth : null;

  if (!resolvedUrl || !inlineUrl) {
    return (
      <div className="flex items-center justify-center rounded-lg border p-8 text-muted-foreground">
        <p>{t("viewer.loadError")}</p>
      </div>
    );
  }

  // Get the appropriate icon for Office files
  const OfficeIcon = isExcel ? FileSpreadsheet : isPowerPoint ? Presentation : FileText;
  const iconColor = isExcel ? "text-green-600" : isPowerPoint ? "text-orange-500" : "text-blue-600";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-muted-foreground text-sm">
          <span className="font-medium">{fileTypeLabel}</span>
          {displayFileSize && <span className="ml-2">({formatBytes(displayFileSize)})</span>}
          {displayFilename && (
            <span className="ml-2 inline-block max-w-50 truncate align-bottom">
              {displayFilename}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {versions && versions.length > 0 && (
            <Popover open={versionsOpen} onOpenChange={setVersionsOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant={isViewingCurrent ? "outline" : "secondary"}
                  size="sm"
                  aria-label={t("versions.label")}
                >
                  <History className="h-4 w-4" />
                  {t("versions.label")}
                  {versions.length > 1 && (
                    <Badge variant="secondary" className="px-1.5">
                      {versions.length}
                    </Badge>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80 p-0">
                <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                  <span className="font-medium text-sm">{t("versions.label")}</span>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7"
                      onClick={() => versionInputRef.current?.click()}
                      disabled={uploadVersion.isPending}
                    >
                      {uploadVersion.isPending ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Upload className="h-3.5 w-3.5" />
                      )}
                      {t("versions.uploadNew")}
                    </Button>
                  )}
                </div>
                <div className="max-h-72 overflow-y-auto py-1">
                  {versions.map((v) => {
                    const isSelected = selectedVersion?.id === v.id;
                    return (
                      <div
                        key={v.id}
                        className={cn(
                          "flex items-center gap-1 px-1.5",
                          isSelected && "bg-accent/60"
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => handleSelectVersion(v)}
                          className="flex flex-1 items-center gap-2 rounded px-1.5 py-1.5 text-left text-sm hover:bg-accent"
                        >
                          <span className="flex-1 truncate">
                            <VersionLabel number={v.version_number} createdAt={v.created_at} />
                          </span>
                          {v.is_current && (
                            <Badge variant="outline" className="shrink-0">
                              {t("versions.current")}
                            </Badge>
                          )}
                        </button>
                        {canDeleteVersions && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                            onClick={() => setVersionPendingDelete(v)}
                            disabled={!hasMultipleVersions || deleteVersion.isPending}
                            aria-label={t("versions.deleteVersion")}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </PopoverContent>
            </Popover>
          )}
          <Button variant="outline" size="sm" onClick={handleOpenInNewTab}>
            <ExternalLink className="h-4 w-4" />
            {t("viewer.openNewTab")}
          </Button>
          <Button variant="outline" size="sm" onClick={handleDownload}>
            <Download className="h-4 w-4" />
            {t("viewer.download")}
          </Button>
        </div>
      </div>
      {!isViewingCurrent && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-700 text-sm dark:text-amber-400">
          {t(canEdit ? "versions.viewingOldCanEdit" : "versions.viewingOld")}
        </div>
      )}
      <input
        ref={versionInputRef}
        type="file"
        className="hidden"
        onChange={handleVersionFileSelected}
      />
      <ConfirmDialog
        open={versionPendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setVersionPendingDelete(null);
        }}
        title={t("versions.deleteVersion")}
        description={
          versionPendingDelete
            ? t("versions.deleteConfirm", { number: versionPendingDelete.version_number })
            : undefined
        }
        confirmLabel={t("versions.deleteVersion")}
        cancelLabel={t("common:cancel")}
        onConfirm={handleConfirmDeleteVersion}
        isLoading={deleteVersion.isPending}
        destructive
      />

      <div
        className="w-full min-w-0 overflow-hidden rounded-lg border bg-card"
        style={baseWidth ? { maxWidth: baseWidth } : undefined}
      >
        {isPdf ? (
          <div className="flex w-full flex-col overflow-hidden">
            {/* PDF Controls */}
            <div
              ref={toolbarRef}
              className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/50 px-4 py-2"
            >
              <span className="text-muted-foreground text-sm">
                {numPages ? t("viewer.pageCount", { count: numPages }) : t("viewer.loading")}
              </span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={zoomOut} disabled={scale <= 0.5}>
                  <ZoomOut className="h-4 w-4" />
                </Button>
                <span className="w-16 text-center text-sm">{Math.round(scale * 100)}%</span>
                <Button variant="outline" size="sm" onClick={zoomIn} disabled={scale >= 2.5}>
                  <ZoomIn className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* PDF Viewer */}
            <div
              className="min-w-0 overflow-auto bg-neutral-100 p-4 dark:bg-neutral-900"
              style={{ height: "70vh", minHeight: 500, maxWidth: "100%" }}
            >
              {pdfError ? (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <FileText className="mb-4 h-16 w-16 text-muted-foreground" />
                  <p className="mb-4 text-muted-foreground">{pdfError}</p>
                  <Button onClick={handleDownload}>
                    <Download className="h-4 w-4" />
                    {t("viewer.downloadPdf")}
                  </Button>
                </div>
              ) : baseWidth ? (
                <Document
                  file={inlineUrl}
                  options={PDF_OPTIONS}
                  // react-pdf 11 suspends while loading and throws failures to the
                  // nearest Error Boundary by default. The viewer handles both
                  // itself — the spinner below and the download fallback above —
                  // so neither escapes into the surrounding page.
                  suspense={false}
                  onLoadSuccess={onDocumentLoadSuccess}
                  onLoadError={onDocumentLoadError}
                  loading={
                    <div className="flex h-full items-center justify-center">
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                  }
                >
                  <div className="flex flex-col items-center gap-4">
                    {pageScale === null ? (
                      <div className="flex items-center justify-center p-8">
                        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                      </div>
                    ) : (
                      Array.from({ length: numPages || 0 }, (_, index) => (
                        <Page
                          // biome-ignore lint/suspicious/noArrayIndexKey: Page numbers are stable and 1-based, so using index as key is fine.
                          key={index + 1}
                          pageNumber={index + 1}
                          scale={pageScale}
                          loading={
                            <div className="flex items-center justify-center p-8">
                              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                            </div>
                          }
                        />
                      ))
                    )}
                  </div>
                </Document>
              ) : (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              )}
            </div>
          </div>
        ) : isText ? (
          // Use iframe for text files
          <iframe
            src={inlineUrl}
            className="w-full bg-muted"
            style={{ height: "70vh", minHeight: 500 }}
            title={originalFilename || t("viewer.textDocument")}
            referrerPolicy="no-referrer"
          />
        ) : isHtml ? (
          // Use sandboxed iframe for HTML files
          <iframe
            src={inlineUrl}
            className="w-full"
            style={{ height: "70vh", minHeight: 500 }}
            title={originalFilename || t("viewer.htmlDocument")}
            sandbox=""
            referrerPolicy="no-referrer"
          />
        ) : isImage ? (
          <>
            <button
              type="button"
              className="flex w-full cursor-zoom-in items-center justify-center overflow-auto bg-muted/50"
              style={{ height: "70vh", minHeight: 500 }}
              onClick={() => setLightboxOpen(true)}
            >
              <img
                src={inlineUrl}
                alt={originalFilename || t("viewer.image")}
                className="max-h-full max-w-full object-contain"
                referrerPolicy="no-referrer"
              />
            </button>
            <Lightbox
              open={lightboxOpen}
              onOpenChange={setLightboxOpen}
              items={inlineUrl ? [{ id: fileId, src: inlineUrl, alt: originalFilename || "" }] : []}
              index={0}
              onIndexChange={() => {}}
            />
          </>
        ) : isVideo ? (
          <div
            className="flex w-full items-center justify-center bg-black"
            style={{ height: "70vh", minHeight: 500 }}
          >
            {/* biome-ignore lint/a11y/useMediaCaption: an uploaded video brings no caption track. */}
            <video
              src={inlineUrl}
              controls
              preload="metadata"
              className="max-h-full max-w-full"
              title={originalFilename || t("viewer.video")}
            />
          </div>
        ) : isAudio ? (
          <div className="flex flex-col items-center justify-center gap-6 bg-muted/50 px-6 py-16">
            <h3 className="font-semibold text-xl tracking-tight">
              {originalFilename || t("viewer.audio")}
            </h3>
            {/* biome-ignore lint/a11y/useMediaCaption: an uploaded recording brings no caption track. */}
            <audio
              src={inlineUrl}
              controls
              preload="metadata"
              className="w-full max-w-xl"
              title={originalFilename || t("viewer.audio")}
            />
          </div>
        ) : isMarkdown ? (
          <div className="flex flex-col">
            <div className="flex items-center justify-between border-b bg-muted/50 px-4 py-2">
              <span className="text-muted-foreground text-sm">{t("viewer.markdownDocument")}</span>
              <Button variant="ghost" size="sm" onClick={() => setShowRendered((prev) => !prev)}>
                {showRendered ? t("viewer.showSource") : t("viewer.showRendered")}
              </Button>
            </div>
            <div className="overflow-auto p-6" style={{ height: "70vh", minHeight: 500 }}>
              {markdownContent === null ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : showRendered ? (
                <Markdown content={markdownContent} />
              ) : (
                <pre className="whitespace-pre-wrap font-mono text-muted-foreground text-sm">
                  {markdownContent}
                </pre>
              )}
            </div>
          </div>
        ) : isOffice ? (
          // Office files - show preview card with download options
          <div
            className="flex flex-col items-center justify-center bg-muted/50"
            style={{ height: "70vh", minHeight: 500 }}
          >
            <OfficeIcon className={`h-24 w-24 ${iconColor} mb-6`} />
            <h3 className="mb-2 font-semibold text-xl tracking-tight">
              {originalFilename || t("viewer.file")}
            </h3>
            <p className="mb-6 max-w-md text-center text-muted-foreground">
              {t("viewer.cannotPreview", { fileType: fileTypeLabel })}
              <br />
              {t("viewer.downloadToView", {
                app: isWord
                  ? "Microsoft Word"
                  : isExcel
                    ? "Microsoft Excel"
                    : "Microsoft PowerPoint",
              })}
            </p>
            <div className="flex gap-3">
              <Button onClick={handleDownload}>
                <Download className="h-4 w-4" />
                {t("viewer.downloadFileType", { fileType: fileTypeLabel })}
              </Button>
              <Button variant="outline" onClick={handleOpenInNewTab}>
                <ExternalLink className="h-4 w-4" />
                {t("viewer.openNewTab")}
              </Button>
            </div>
          </div>
        ) : (
          // Unknown file type - show generic download prompt
          <div
            className="flex flex-col items-center justify-center bg-muted/50"
            style={{ height: "70vh", minHeight: 500 }}
          >
            <FileText className="mb-6 h-24 w-24 text-muted-foreground" />
            <h3 className="mb-2 font-semibold text-xl tracking-tight">
              {originalFilename || t("viewer.file")}
            </h3>
            <p className="mb-6 text-muted-foreground">{t("viewer.unknownFileType")}</p>
            <Button onClick={handleDownload}>
              <Download className="h-4 w-4" />
              {t("viewer.downloadFile")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};
