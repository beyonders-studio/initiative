import { Capacitor } from "@capacitor/core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PhotoCaptureError } from "@/ui/host";

import { canCapturePhoto, capturePhoto } from "./nativeCamera";

const takePhoto = vi.fn();
const chooseFromGallery = vi.fn();

vi.mock("@capacitor/camera", () => ({
  Camera: {
    takePhoto: (...args: unknown[]) => takePhoto(...args),
    chooseFromGallery: (...args: unknown[]) => chooseFromGallery(...args),
  },
  MediaTypeSelection: { Photo: 0, Video: 1, All: 2 },
}));

/** The plugin rejects with an Error carrying a `code`; mirror that shape. */
const pluginError = (code: string, message = "plugin error") =>
  Object.assign(new Error(message), { code });

const native = (value: boolean) => vi.spyOn(Capacitor, "isNativePlatform").mockReturnValue(value);

const respondWith = (blob: Blob) =>
  vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(blob, { headers: { "Content-Type": blob.type } }));

beforeEach(() => {
  takePhoto.mockReset();
  chooseFromGallery.mockReset();
});

describe("canCapturePhoto", () => {
  it("is false in a browser", () => {
    native(false);
    expect(canCapturePhoto()).toBe(false);
  });

  it("is true on the native app", () => {
    native(true);
    expect(canCapturePhoto()).toBe(true);
  });
});

describe("capturePhoto", () => {
  it("refuses off-native rather than opening anything", async () => {
    native(false);
    await expect(capturePhoto("camera")).rejects.toMatchObject({ reason: "unavailable" });
    expect(takePhoto).not.toHaveBeenCalled();
  });

  it("returns the captured photo as an uploadable file", async () => {
    native(true);
    takePhoto.mockResolvedValue({ webPath: "capacitor://localhost/photo", saved: false });
    respondWith(new Blob(["binary"], { type: "image/jpeg" }));

    const file = await capturePhoto("camera");

    expect(file).toBeInstanceOf(File);
    expect(file?.type).toBe("image/jpeg");
    expect(file?.name).toMatch(/^photo-\d+\.jpg$/);
    expect(takePhoto).toHaveBeenCalledWith(
      expect.objectContaining({ correctOrientation: true, quality: 90 })
    );
  });

  it("names the file for the format that came back", async () => {
    native(true);
    takePhoto.mockResolvedValue({ webPath: "capacitor://localhost/photo" });
    respondWith(new Blob(["binary"], { type: "image/png" }));

    expect((await capturePhoto("camera"))?.name).toMatch(/\.png$/);
  });

  it("reads the first picture chosen from the library", async () => {
    native(true);
    chooseFromGallery.mockResolvedValue({
      results: [{ webPath: "capacitor://localhost/one" }, { webPath: "capacitor://localhost/two" }],
    });
    const fetchSpy = respondWith(new Blob(["binary"], { type: "image/webp" }));

    const file = await capturePhoto("library");

    expect(file?.name).toMatch(/\.webp$/);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith("capacitor://localhost/one");
  });

  it("converts a native uri when there is no web path", async () => {
    native(true);
    vi.spyOn(Capacitor, "convertFileSrc").mockReturnValue("http://localhost/_capacitor_file_/x");
    takePhoto.mockResolvedValue({ uri: "file:///storage/x.jpg" });
    const fetchSpy = respondWith(new Blob(["binary"], { type: "image/jpeg" }));

    await capturePhoto("camera");

    expect(fetchSpy).toHaveBeenCalledWith("http://localhost/_capacitor_file_/x");
  });

  it("treats an empty gallery selection as backing out", async () => {
    native(true);
    chooseFromGallery.mockResolvedValue({ results: [] });

    await expect(capturePhoto("library")).resolves.toBeNull();
  });

  it.each([
    ["OS-PLUG-CAMR-0006", "the camera"],
    ["OS-PLUG-CAMR-0020", "the gallery"],
  ])("returns nothing when %s cancels %s", async (code) => {
    native(true);
    takePhoto.mockRejectedValue(pluginError(code, "User cancelled"));

    await expect(capturePhoto("camera")).resolves.toBeNull();
  });

  it("returns nothing when only the message says it was cancelled", async () => {
    native(true);
    takePhoto.mockRejectedValue(new Error("User cancelled photos app"));

    await expect(capturePhoto("camera")).resolves.toBeNull();
  });

  it("reports a denied camera permission as such", async () => {
    native(true);
    takePhoto.mockRejectedValue(pluginError("OS-PLUG-CAMR-0003"));

    await expect(capturePhoto("camera")).rejects.toMatchObject({ reason: "permission" });
  });

  it("reports a denied gallery permission as such", async () => {
    native(true);
    chooseFromGallery.mockRejectedValue(pluginError("OS-PLUG-CAMR-0005"));

    await expect(capturePhoto("library")).rejects.toMatchObject({ reason: "permission" });
  });

  it("reports a device with no camera", async () => {
    native(true);
    takePhoto.mockRejectedValue(pluginError("OS-PLUG-CAMR-0007"));

    await expect(capturePhoto("camera")).rejects.toMatchObject({ reason: "unavailable" });
  });

  it("reports anything else as a failure", async () => {
    native(true);
    takePhoto.mockRejectedValue(pluginError("OS-PLUG-CAMR-0010"));

    await expect(capturePhoto("camera")).rejects.toBeInstanceOf(PhotoCaptureError);
  });

  it("fails when the captured photo cannot be read back", async () => {
    native(true);
    takePhoto.mockResolvedValue({ webPath: "capacitor://localhost/photo" });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 404 }));

    await expect(capturePhoto("camera")).rejects.toMatchObject({ reason: "failed" });
  });

  it("fails when the result points at nothing", async () => {
    native(true);
    takePhoto.mockResolvedValue({ saved: false });

    await expect(capturePhoto("camera")).rejects.toMatchObject({ reason: "failed" });
  });
});
