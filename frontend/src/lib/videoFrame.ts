/** The longest side of a frame drawn for a video's thumbnail. */
const FRAME_EDGE = 640;

/** How long the video may take to reach the frame before it is given up. */
const FRAME_TIMEOUT_MS = 30_000;

/**
 * One frame of the video at `url`, a second in (or a tenth of the way through
 * a shorter one), drawn no larger than the thumbnail edge: a WebP where the
 * browser writes one, otherwise a PNG.
 *
 * Rejects where the video cannot be read, where the browser keeps its pixels
 * from the page (a video served from another origin), when `signal` aborts
 * before the frame is ready, and when it takes longer than
 * {@link FRAME_TIMEOUT_MS}. The video stops loading whichever way it ends.
 */
export const drawVideoFrame = (url: string, signal?: AbortSignal): Promise<Blob> =>
  new Promise((resolve, reject) => {
    const video = document.createElement("video");
    let settled = false;
    const unload = () => {
      video.removeAttribute("src");
      video.load();
    };
    const settle = (finish: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      signal?.removeEventListener("abort", abandon);
      unload();
      finish();
    };
    const fail = (error: unknown) => settle(() => reject(error));
    const abandon = () => fail(new Error("the frame was abandoned"));
    const timeout = setTimeout(abandon, FRAME_TIMEOUT_MS);
    if (signal?.aborted) {
      abandon();
      return;
    }
    signal?.addEventListener("abort", abandon);

    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.onerror = () => fail(new Error("the video could not be read"));
    video.onloadedmetadata = () => {
      video.currentTime = Math.min(1, (video.duration || 0) / 10);
    };
    video.onseeked = () => {
      const scale = Math.min(1, FRAME_EDGE / Math.max(video.videoWidth, video.videoHeight, 1));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      try {
        canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
        // The frame is on the canvas; the video need load no further.
        unload();
        canvas.toBlob(
          (frame) => (frame ? settle(() => resolve(frame)) : fail(new Error("no frame was drawn"))),
          "image/webp",
          0.85
        );
      } catch (error) {
        fail(error);
      }
    };
    video.src = url;
  });
