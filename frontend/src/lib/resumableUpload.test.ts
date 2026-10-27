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
      { initiativeId: 4 },
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
      { initiativeId: 4 },
      async (uploadId) => uploadId
    );
    await vi.advanceTimersByTimeAsync(4_000);

    await expect(sending).resolves.toMatch(/^up-/);
    expect(offsets).toEqual(["0", "0"]);
    expect(asked).toBe(2);
    vi.useRealTimers();
  });

  it("throws the upload away when it is stopped, once the piece lets go of it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const thrownAway = vi.fn();
    const stop = new AbortController();
    server.use(
      communityHttp.patch("/resumable-uploads/:id", () => {
        stop.abort();
        return new HttpResponse(null, { status: 204, headers: { "Upload-Offset": "2" } });
      }),
      // The stopped piece still holds it the first time.
      communityHttp.delete("/resumable-uploads/:id", () => {
        thrownAway();
        return new HttpResponse(null, { status: thrownAway.mock.calls.length === 1 ? 423 : 204 });
      })
    );

    await expect(
      uploadInPieces(
        3,
        new File(["a report"], "draft.pdf"),
        "draft.pdf",
        { fileId: 9 },
        async (uploadId) => uploadId,
        { signal: stop.signal }
      )
    ).rejects.toBeDefined();
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.waitFor(() => expect(thrownAway).toHaveBeenCalledTimes(2));
    vi.useRealTimers();
  });
});
