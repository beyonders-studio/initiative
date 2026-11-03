import { apiClient } from "@/api/client";
import { downloadBlob } from "@/lib/csv";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/** Recover the server-chosen filename from a Content-Disposition header —
 * the single source of truth for export names (a file passthrough keeps an
 * extension the client can't know; bundles arrive as ``.zip`` regardless of
 * format). Handles both the plain ``filename="…"`` and the RFC 5987
 * ``filename*=utf-8''…`` forms; null when absent. */
export function filenameFromDisposition(header: string | undefined): string | null {
  if (!header) {
    return null;
  }
  const extended = header.match(/filename\*=utf-8''([^;]+)/i);
  if (extended) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      // fall through to the plain form
    }
  }
  const plain = header.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : null;
}

/** Client-side fallback stem for export downloads: the slugified resource
 * name plus today's date, mirroring the server's naming convention. Only a
 * fallback — the server's Content-Disposition name wins when present. */
export function exportFilenameStem(name: string, fallback: string): string {
  const slug =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || fallback;
  return `${slug}-${new Date().toISOString().slice(0, 10)}`;
}

/** Axios error bodies arrive as Blobs under responseType "blob"; recover the
 * JSON detail so getErrorMessage can map it to a localized message. */
export async function normalizeBlobError(err: unknown): Promise<unknown> {
  const response = (err as { response?: { data?: unknown } })?.response;
  if (response?.data instanceof Blob) {
    try {
      response.data = JSON.parse(await response.data.text());
    } catch {
      // keep the original error
    }
  }
  return err;
}

/** Fetch a finished export job's artifact and hand it to the browser as a
 * download. Shared by the export button and `openNotification` — the loose
 * ``t`` shape (same as NotificationBell's helpers) admits any caller's bound
 * namespaces, since the toast keys here are namespace-prefixed. */
export async function downloadExportArtifact(
  communityId: number,
  jobId: number,
  t: (key: string, options?: Record<string, unknown>) => string,
  source = "tasks",
  format: string | null = "pdf"
): Promise<void> {
  try {
    const res = await apiClient.get<Blob>(`/c/${communityId}/exports/jobs/${jobId}/download`, {
      responseType: "blob",
    });
    const serverName = filenameFromDisposition(res.headers["content-disposition"]);
    downloadBlob(res.data, serverName ?? `${source}-${jobId}.${format ?? "pdf"}`);
    toast.success(t("exports:export.success"));
  } catch (err) {
    toast.error(getErrorMessage(await normalizeBlobError(err), "exports:export.error"));
  }
}
