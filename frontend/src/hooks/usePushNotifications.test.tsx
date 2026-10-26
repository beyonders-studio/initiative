import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { usePushTray } from "./usePushNotifications";

const clearTray = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("@capacitor/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@capacitor/core")>();
  return { ...actual, Capacitor: { ...actual.Capacitor, getPlatform: () => "ios" } };
});
vi.mock("@capacitor/push-notifications", () => ({
  PushNotifications: { removeAllDeliveredNotifications: clearTray },
}));

const Probe = () => {
  usePushTray();
  return null;
};

const serveUnread = (count: number) =>
  server.use(
    http.get("/api/v1/notifications/", () =>
      HttpResponse.json({
        notifications: count ? [buildNotification()] : [],
        unread_count: count,
        next_cursor: null,
      })
    )
  );

describe("usePushTray", () => {
  beforeEach(() => {
    clearTray.mockClear();
  });

  it("empties the tray once the bell has nothing unread", async () => {
    serveUnread(0);
    renderWithProviders(<Probe />);

    await waitFor(() => expect(clearTray).toHaveBeenCalled());
  });

  it("leaves the tray while something is unread, and empties it on signing out", async () => {
    serveUnread(2);
    const { unmount } = renderWithProviders(<Probe />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(clearTray).not.toHaveBeenCalled();
    unmount();
    expect(clearTray).toHaveBeenCalledOnce();
  });
});
