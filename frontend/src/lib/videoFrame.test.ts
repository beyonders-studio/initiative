import { afterEach, describe, expect, it, vi } from "vitest";

import { drawVideoFrame } from "./videoFrame";

/** A video and a canvas whose events the test fires itself. */
const fakeElements = () => {
  const video = {
    muted: false,
    playsInline: false,
    preload: "",
    src: "",
    currentTime: 0,
    duration: 20,
    videoWidth: 1280,
    videoHeight: 720,
    removeAttribute: vi.fn(),
    load: vi.fn(),
    onerror: null as (() => void) | null,
    onloadedmetadata: null as (() => void) | null,
    onseeked: null as (() => void) | null,
  };
  let finishBlob: ((frame: Blob | null) => void) | null = null;
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage: vi.fn() }),
    toBlob: (callback: (frame: Blob | null) => void) => {
      finishBlob = callback;
    },
  };
  vi.spyOn(document, "createElement").mockImplementation(
    (tag: string) => (tag === "video" ? video : canvas) as unknown as HTMLElement
  );
  return { video, canvas, finishBlob: (frame: Blob | null) => finishBlob?.(frame) };
};

describe("drawVideoFrame", () => {
  afterEach(() => vi.restoreAllMocks());

  it("draws a frame a second in, no wider than the thumbnail edge", async () => {
    const { video, canvas, finishBlob } = fakeElements();
    const drawn = drawVideoFrame("/clip.mp4");

    video.onloadedmetadata?.();
    expect(video.currentTime).toBe(1);
    video.onseeked?.();
    const frame = new Blob(["frame"]);
    finishBlob(frame);

    await expect(drawn).resolves.toBe(frame);
    expect([canvas.width, canvas.height]).toEqual([640, 360]);
  });

  it("gives up a frame the viewer left while it was being written", async () => {
    const { video, finishBlob } = fakeElements();
    const leaving = new AbortController();
    const drawn = drawVideoFrame("/clip.mp4", leaving.signal);

    video.onloadedmetadata?.();
    video.onseeked?.();
    leaving.abort();
    finishBlob(new Blob(["frame"]));

    await expect(drawn).rejects.toThrow("abandoned");
    expect(video.removeAttribute).toHaveBeenCalledWith("src");
  });
});
