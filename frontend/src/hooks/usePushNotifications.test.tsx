import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { useMarkNotificationRead } from "./useNotifications";
import { usePushTray } from "./usePushNotifications";

const clearTray = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("@capacitor/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@capacitor/core")>();
  return { ...actual, Capacitor: { ...actual.Capacitor, getPlatform: () => "ios" } };
});
vi.mock("@capacitor/push-notifications", () => ({
  PushNotifications: { removeAllDeliveredNotifications: clearTray },
}));

let markRead: (id: number) => void = () => {};

const Probe = () => {
  usePushTray();
  markRead = useMarkNotificationRead().mutate;
  return null;
};

const line = buildNotification({ id: 7, read_at: null });

const serveUnread = (count: number) => {
  const fetched = vi.fn();
  server.use(
    http.get("/api/v1/notifications/", () => {
      fetched();
      return HttpResponse.json({
        notifications: count ? [line] : [],
        unread_count: count,
        next_cursor: null,
      });
    })
  );
  return fetched;
};

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

  it("keeps the tray when marking the last line read fails", async () => {
    const fetched = serveUnread(1);
    let answer = () => {};
    server.use(
      http.post(
        "/api/v1/notifications/7/read",
        () =>
          new Promise<Response>((resolve) => {
            answer = () => resolve(new HttpResponse(null, { status: 500 }));
          })
      )
    );
    const { queryClient } = renderWithProviders(<Probe />);
    await waitFor(() => expect(fetched).toHaveBeenCalledOnce());

    markRead(7);
    // The bell shows the read before the server has answered.
    await waitFor(() =>
      expect(queryClient.getQueryData(["/api/v1/notifications/", { limit: 50 }])).toMatchObject({
        unread_count: 0,
      })
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    answer();

    // The failure refetches the count the server still holds.
    await waitFor(() => expect(fetched).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(clearTray).not.toHaveBeenCalled();
  });
});
