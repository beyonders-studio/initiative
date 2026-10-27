import { isAxiosError } from "axios";

import { apiClient } from "@/api/client";
import { getItem, removeItem, setItem } from "@/lib/storage";

/** The most the server takes in one request. */
const PIECE_BYTES = 50 * 1024 * 1024;
const TUS = { "Tus-Resumable": "1.0.0" };
/** How long to wait before each new try of a piece that did not arrive. The
 *  last outlasts the hold a dropped request leaves on the upload. */
const RETRY_DELAYS_MS = [1_000, 3_000, 10_000, 30_000, 60_000];

/** Where a file sent in pieces is going: a new file in an initiative, or a
 *  new version of a file. */
export type ResumableTarget = { initiativeId: number } | { fileId: number };

export interface ResumableOptions {
  /** Called as bytes arrive, with how many of the file's have. */
  onProgress?: (sent: number, total: number) => void;
  /** Stops sending and throws the upload away. */
  signal?: AbortSignal;
}

const metadata = (values: Record<string, string>) =>
  Object.entries(values)
    .map(([key, value]) => {
      const bytes = new TextEncoder().encode(value);
      return `${key} ${btoa(String.fromCharCode(...bytes))}`;
    })
    .join(",");

/** Whether trying again from where the server stands can help. */
const retryable = (error: unknown) => {
  if (!isAxiosError(error)) return false;
  const status = error.response?.status;
  return status === undefined || status >= 500 || status === 409 || status === 423;
};

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true }
    );
  });

/**
 * Send `file` to the community a piece at a time, then hand its upload id to
 * `take`, the endpoint that keeps it, and answer what that answers.
 *
 * A piece that does not arrive is tried again from where the server says the
 * upload stands. The upload is remembered until it is taken, so picking the
 * same file again for the same place, after a reload or a refusal, carries on
 * from there rather than sending it all again. Aborting throws it away.
 */
export const uploadInPieces = async <T>(
  communityId: number,
  file: Blob,
  filename: string,
  target: ResumableTarget,
  take: (uploadId: string) => Promise<T>,
  { onProgress, signal }: ResumableOptions = {}
): Promise<T> => {
  const base = `/c/${communityId}/resumable-uploads`;
  const where = "fileId" in target ? `file-${target.fileId}` : `in-${target.initiativeId}`;
  const changed = file instanceof File ? file.lastModified : 0;
  const remembered = `resumable-upload:${communityId}:${where}:${filename}:${file.size}:${changed}`;

  const standing = async (id: string): Promise<number | null> => {
    try {
      const answer = await apiClient.head(`${base}/${id}`, { headers: TUS, signal });
      return Number(answer.headers["upload-offset"]);
    } catch (error) {
      if (isAxiosError(error) && [403, 404, 410].includes(error.response?.status ?? 0)) {
        return null;
      }
      throw error;
    }
  };

  let id = getItem(remembered);
  let offset = id ? await standing(id) : null;
  try {
    if (id === null || offset === null) {
      const created = await apiClient.post(base, null, {
        headers: {
          ...TUS,
          "Upload-Length": String(file.size),
          "Upload-Metadata": metadata({
            purpose: "file",
            filename,
            ...("fileId" in target
              ? { file_id: String(target.fileId) }
              : { initiative_id: String(target.initiativeId) }),
          }),
        },
        signal,
      });
      id = String(created.headers.location).split("/").pop() ?? "";
      offset = 0;
      await setItem(remembered, id);
    }
    const uploadId = id;
    let failures = 0;
    while (offset < file.size) {
      const from: number = offset;
      try {
        const answer = await apiClient.patch(
          `${base}/${uploadId}`,
          file.slice(from, from + PIECE_BYTES),
          {
            headers: {
              ...TUS,
              "Upload-Offset": String(from),
              "Content-Type": "application/offset+octet-stream",
            },
            signal,
            onUploadProgress: ({ loaded }) => onProgress?.(from + loaded, file.size),
          }
        );
        offset = Number(answer.headers["upload-offset"]);
        failures = 0;
      } catch (error) {
        if (signal?.aborted || !retryable(error) || failures >= RETRY_DELAYS_MS.length) {
          throw error;
        }
        await wait(RETRY_DELAYS_MS[failures++], signal);
        const found = await standing(uploadId);
        if (found === null) throw error;
        offset = found;
      }
    }
    onProgress?.(file.size, file.size);
    const taken = await take(uploadId);
    await removeItem(remembered);
    return taken;
  } catch (error) {
    if (signal?.aborted && id) {
      await removeItem(remembered);
      void apiClient.delete(`${base}/${id}`, { headers: TUS }).catch(() => undefined);
    }
    throw error;
  }
};
