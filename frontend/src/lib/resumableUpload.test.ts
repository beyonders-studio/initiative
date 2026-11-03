import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";

import { uploadInPieces } from "./resumableUpload";

describe("uploadInPieces", () => {
  it("sends the file, then hands its upload to the endpoint that keeps it", async () => {
    const take = vi.fn(async (uploadId: string) => ({ uploadId }));
    const progress: number[] = [];

    const kept = await uploadInPieces(
      3,
      new File(["a report"], "report.pdf"),
      "report.pdf",
      { purpose: "file", initiativeId: 4 },
      take,
      { onProgress: (sent) => progress.push(sent) }
    );

    expect(kept.uploadId).toMatch(/^up-/);
    expect(progress.at(-1)).toBe(8);
  });

  it("carries on from where the server stands once the connection is back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const offsets: string[] = [];
    let dropped = false;
    let asked = 0;
    server.use(
      communityHttp.patch("/resumable-uploads/:id", ({ request }) => {
        offsets.push(request.headers.get("upload-offset") ?? "");
        if (!dropped) {
          dropped = true;
          return HttpResponse.error();
        }
        return new HttpResponse(null, { status: 204, headers: { "Upload-Offset": "8" } });
      }),
      // Still down the first time it asks where the upload stands.
      communityHttp.head("/resumable-uploads/:id", () =>
        asked++ === 0
          ? HttpResponse.error()
          : new HttpResponse(null, { headers: { "Upload-Offset": "0" } })
      )
    );

    const sending = uploadInPieces(
      3,
      new File(["a report"], "minutes.pdf"),
      "minutes.pdf",
      { purpose: "file", initiativeId: 4 },
      async (uploadId) => uploadId
    );
    await vi.advanceTimersByTimeAsync(4_000);

    await expect(sending).resolves.toMatch(/^up-/);
    expect(offsets).toEqual(["0", "0"]);
    expect(asked).toBe(2);
    vi.useRealTimers();
  });

  it("throws a stopped upload away, and starts afresh when the file is picked again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const thrownAway: string[] = [];
    const stop = new AbortController();
    let stopped: string | null = null;
    server.use(
      communityHttp.patch("/resumable-uploads/:id", ({ params }) => {
        const id = String(params.id);
        stopped ??= id;
        if (id === stopped) stop.abort();
        const offset = id === stopped ? "2" : "8";
        return new HttpResponse(null, { status: 204, headers: { "Upload-Offset": offset } });
      }),
      // The stopped piece still holds it the first time.
      communityHttp.delete("/resumable-uploads/:id", ({ params }) => {
        thrownAway.push(String(params.id));
        return new HttpResponse(null, { status: thrownAway.length === 1 ? 423 : 204 });
      })
    );
    const send = (signal?: AbortSignal) =>
      uploadInPieces(
        3,
        new File(["a report"], "draft.pdf", { lastModified: 1 }),
        "draft.pdf",
        { purpose: "file", fileId: 9 },
        async (uploadId) => uploadId,
        { signal }
      );

    await expect(send(stop.signal)).rejects.toBeDefined();
    const again = await send();
    await vi.advanceTimersByTimeAsync(2_000);

    await vi.waitFor(() => expect(thrownAway).toEqual([stopped, stopped]));
    expect(again).not.toBe(stopped);
    vi.useRealTimers();
  });
});
