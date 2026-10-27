/** The longest side of a frame drawn for a video's thumbnail. */
const FRAME_EDGE = 640;

/**
 * One frame of the video at `url`, a second in (or a tenth of the way through
 * a shorter one), drawn no larger than the thumbnail edge: a WebP where the
 * browser writes one, otherwise a PNG.
 *
 * Rejects where the video cannot be read, and where the browser keeps its
 * pixels from the page (a video served from another origin).
 */
export const drawVideoFrame = (url: string): Promise<Blob> =>
  new Promise((resolve, reject) => {
    const video = document.createElement("video");
    const done = () => {
      video.removeAttribute("src");
      video.load();
    };
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.onerror = () => {
      done();
      reject(new Error("the video could not be read"));
    };
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
        canvas.toBlob(
          (frame) => (frame ? resolve(frame) : reject(new Error("no frame was drawn"))),
          "image/webp",
          0.85
        );
      } catch (error) {
        reject(error);
      } finally {
        done();
      }
    };
    video.src = url;
  });
