import { Capacitor } from "@capacitor/core";

import { PhotoCaptureError, type PhotoCaptureFailure, type PhotoSource } from "@/ui/host";

/**
 * Taking a picture, on the devices that have a camera.
 *
 * The native app can go camera → upload in one step, where the browser can only
 * offer a file field. Everything here answers "no" off-native so a caller can
 * ask once and render the control it can actually deliver.
 */

/** Whether this device can hand back a picture without going through a file field. */
export const canCapturePhoto = (): boolean => Capacitor.isNativePlatform();

/** Error codes the plugin returns; see `CameraErrorCode` in @capacitor/camera. */
const CANCELLED_CODES = new Set([
  "OS-PLUG-CAMR-0006", // take photo cancelled
  "OS-PLUG-CAMR-0013", // edit photo cancelled
  "OS-PLUG-CAMR-0020", // choose media cancelled
]);
const PERMISSION_CODES = new Set([
  "OS-PLUG-CAMR-0003", // camera permission denied
  "OS-PLUG-CAMR-0005", // gallery permission denied
]);
const UNAVAILABLE_CODES = new Set([
  "OS-PLUG-CAMR-0007", // no camera on this device
]);

const MIME_EXTENSIONS: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/heic": "heic",
  "image/heif": "heif",
};

const FALLBACK_MIME = "image/jpeg";

/**
 * Classify a rejected plugin call.
 *
 * The code is the reliable signal; the message is the fallback, because a
 * cancellation reaching the caller as an error would show a failure toast for
 * someone who simply changed their mind.
 */
const classify = (error: unknown): PhotoCaptureFailure | "cancelled" => {
  const code = (error as { code?: unknown })?.code;
  if (typeof code === "string") {
    if (CANCELLED_CODES.has(code)) return "cancelled";
    if (PERMISSION_CODES.has(code)) return "permission";
    if (UNAVAILABLE_CODES.has(code)) return "unavailable";
  }
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  if (message.includes("cancel")) return "cancelled";
  if (message.includes("denied") || message.includes("permission")) return "permission";
  return "failed";
};

/** The picture the plugin points at, read back as a file an upload can take. */
const readMedia = async (media: { webPath?: string; uri?: string }): Promise<File> => {
  const path = media.webPath ?? (media.uri ? Capacitor.convertFileSrc(media.uri) : undefined);
  if (!path) throw new PhotoCaptureError("failed");

  const response = await fetch(path);
  if (!response.ok) throw new PhotoCaptureError("failed");

  const blob = await response.blob();
  const type = blob.type || FALLBACK_MIME;
  const extension = MIME_EXTENSIONS[type] ?? "jpg";
  return new File([blob], `photo-${Date.now()}.${extension}`, { type, lastModified: Date.now() });
};

/**
 * Open the camera (or the device's picture library) and return what was taken.
 *
 * Resolves to `null` when the person backed out, and throws a
 * {@link PhotoCaptureError} when the capture itself could not happen. The
 * plugin is loaded on demand so the browser build never carries it.
 */
export const capturePhoto = async (source: PhotoSource): Promise<File | null> => {
  if (!canCapturePhoto()) throw new PhotoCaptureError("unavailable");

  try {
    const { Camera, MediaTypeSelection } = await import("@capacitor/camera");

    if (source === "camera") {
      // Orientation correction is the plugin's default, but an upside-down
      // upload is the one thing nobody can fix afterwards, so say it.
      const photo = await Camera.takePhoto({ quality: 90, correctOrientation: true });
      return await readMedia(photo);
    }

    const chosen = await Camera.chooseFromGallery({
      mediaType: MediaTypeSelection.Photo,
      allowMultipleSelection: false,
    });
    const [first] = chosen.results;
    return first ? await readMedia(first) : null;
  } catch (error) {
    if (error instanceof PhotoCaptureError) throw error;
    const outcome = classify(error);
    if (outcome === "cancelled") return null;
    throw new PhotoCaptureError(outcome);
  }
};
