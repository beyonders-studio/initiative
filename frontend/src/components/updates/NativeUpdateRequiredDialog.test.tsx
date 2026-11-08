/**
 * When a server's update needs a newer app, the prompt hands over the new app
 * for this device, from the release the update's floor names. A desktop app
 * that can replace itself offers to, and asks whether to keep doing so.
 */
import { Capacitor } from "@capacitor/core";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { autoUpdateConsented } from "@/lib/desktopUpdates";
import { androidApkUrl, desktopInstallerUrl, PLAY_STORE_URL } from "@/lib/links";

import { NativeUpdateRequiredDialog } from "./NativeUpdateRequiredDialog";

const updater = vi.hoisted(() => ({
  supported: vi.fn(async () => ({ supported: false })),
  download: vi.fn(),
  install: vi.fn(),
}));
vi.mock("@/plugins/desktopUpdater", () => ({ default: updater }));

const appEnvironment = vi.hoisted(() => ({
  get: vi.fn(async () => ({}) as { installer?: string }),
}));
vi.mock("@/plugins/appEnvironment", () => ({
  default: appEnvironment,
  PLAY_STORE_INSTALLER: "com.android.vending",
}));

const renderDialog = () =>
  renderWithProviders(
    <NativeUpdateRequiredDialog open version="0.81.0" minNativeVersion="0.80.0" onClose={vi.fn()} />
  );

describe("NativeUpdateRequiredDialog", () => {
  it.each([
    ["android", androidApkUrl("0.80.0")],
    // jsdom says Linux.
    ["electron", desktopInstallerUrl("0.80.0", "linux")],
  ])("offers the new %s app", async (platform, href) => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);
    renderDialog();

    expect(await screen.findByRole("link", { name: /download/i })).toHaveAttribute("href", href);
  });

  it("sends an Android app installed from Google Play back to Play", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("android");
    appEnvironment.get.mockResolvedValueOnce({ installer: "com.android.vending" });
    renderDialog();

    expect(await screen.findByText(/from Google Play/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute("href", PLAY_STORE_URL);
  });

  it("offers no download on Android until it knows where the app came from", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("android");
    let answer: (value: { installer?: string }) => void = () => {};
    appEnvironment.get.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    renderDialog();

    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
    answer({ installer: "com.android.vending" });
    expect(await screen.findByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      PLAY_STORE_URL
    );
  });

  it("sends an iPhone to the App Store, with no download or update of its own", async () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    renderDialog();

    expect(await screen.findByText(/from the App Store/i)).toBeInTheDocument();
    expect(screen.queryByText(/APK/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update now/i })).not.toBeInTheDocument();
  });

  it("updates a desktop app that can replace itself, and keeps doing so", async () => {
    const user = userEvent.setup();
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("electron");
    updater.supported.mockResolvedValue({ supported: true });
    updater.download.mockResolvedValue({ version: "0.80.0" });
    renderDialog();

    expect(await screen.findByRole("checkbox", { name: /always update/i })).toBeChecked();
    await user.click(screen.getByRole("button", { name: /update now/i }));

    expect(updater.download).toHaveBeenCalledWith({ version: "0.80.0" });
    expect(updater.install).toHaveBeenCalled();
    expect(autoUpdateConsented()).toBe(true);
  });

  it("falls back to the download when the update does not finish", async () => {
    const user = userEvent.setup();
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("electron");
    updater.supported.mockResolvedValue({ supported: true });
    updater.download.mockRejectedValue(new Error("offline"));
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /update now/i }));

    expect(await screen.findByText(/didn't finish/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      desktopInstallerUrl("0.80.0", "linux")
    );
    expect(updater.install).not.toHaveBeenCalled();
  });

  it("offers to update again when a later release asks", async () => {
    const user = userEvent.setup();
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("electron");
    updater.supported.mockResolvedValue({ supported: true });
    updater.download.mockRejectedValueOnce(new Error("offline"));
    const { rerender } = renderDialog();
    await user.click(await screen.findByRole("button", { name: /update now/i }));
    await screen.findByText(/didn't finish/i);

    const later = (open: boolean) => (
      <NativeUpdateRequiredDialog
        open={open}
        version="0.82.0"
        minNativeVersion="0.82.0"
        onClose={vi.fn()}
      />
    );
    rerender(later(false));
    rerender(later(true));

    expect(await screen.findByRole("button", { name: /update now/i })).toBeEnabled();
    expect(screen.queryByText(/didn't finish/i)).not.toBeInTheDocument();
  });
});
