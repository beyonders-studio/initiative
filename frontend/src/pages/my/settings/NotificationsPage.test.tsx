import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { buildNotificationPreferences } from "@/__tests__/helpers/handlers/notification.handlers";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage as renderRoutedPage } from "@/__tests__/helpers/render";
import type { NotificationPreferencesUpdate } from "@/api/generated/initiativeAPI.schemas";

// usePushNotifications pulls in a Capacitor plugin that can't load in jsdom.
vi.mock("@/hooks/usePushNotifications", () => ({
  usePushNotifications: () => ({
    permissionStatus: "prompt",
    requestPermission: vi.fn(),
    isSupported: false,
  }),
}));

import { NotificationsPage } from "./NotificationsPage";

describe("NotificationsPage", () => {
  const renderPage = (overrides = {}) =>
    renderRoutedPage(() => (
      <NotificationsPage
        user={buildUser({ event_reminder_minutes_before: 15, ...overrides })}
        refreshUser={vi.fn().mockResolvedValue(undefined)}
      />
    ));

  it("renders the grid from the registry the server sends, on the bell and the desktop", async () => {
    renderPage();
    expect(await screen.findByText("In your communities")).toBeInTheDocument();
    expect(screen.getByText("Mentions and replies")).toBeInTheDocument();
    expect(screen.getByText("Assigned to you")).toBeInTheDocument();
    expect(screen.getByText("Subscribed")).toBeInTheDocument();
    expect(screen.getByText("Needs you")).toBeInTheDocument();
    // Nothing switches cases off, so there is no row to show.
    expect(screen.queryByText("Cases")).not.toBeInTheDocument();

    expect(screen.getByLabelText("Mentions and replies on Bell")).toBeInTheDocument();
    // A server with no phone push offers the desktop and no mobile column.
    expect(screen.getByLabelText("Mentions and replies on Desktop")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mentions and replies on Mobile")).not.toBeInTheDocument();
    // The bell stays on and unswitchable for account notices.
    const bell = screen.getByLabelText("Your account on Bell");
    expect(bell).toBeDisabled();
    expect(bell).toBeChecked();
  });

  it.each([
    [30, "30 minutes before"],
    [0, "At the time of the event"],
  ])("shows a reminder lead time of %i as %s", async (minutes, label) => {
    renderPage({ event_reminder_minutes_before: minutes });
    // The Radix Select trigger renders the selected option's label.
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  const serve = (preferences = buildNotificationPreferences()) => {
    const sent: NotificationPreferencesUpdate[] = [];
    server.use(
      http.get("/api/v1/me/notification-preferences", () => HttpResponse.json(preferences)),
      http.put("/api/v1/me/notification-preferences", async ({ request }) => {
        sent.push((await request.json()) as NotificationPreferencesUpdate);
        return HttpResponse.json(preferences);
      })
    );
    return sent;
  };

  describe("digests", () => {
    it("lists each digest apart from the grid, with no bell of its own", async () => {
      serve();
      renderPage();

      expect(await screen.findByLabelText("Overdue tasks on Email")).toBeChecked();
      // Asked for, never sent unbidden.
      expect(screen.getByLabelText("Coming up on Email")).not.toBeChecked();
      expect(screen.queryByLabelText("Overdue tasks on Bell")).not.toBeInTheDocument();
      // An email time is asked for only where email is gathered.
      expect(document.getElementById("email-time")).toBeNull();
    });

    it("keeps a time for each digest, and writes the one that moved", async () => {
      const user = userEvent.setup();
      const sent = serve();
      renderPage();

      await screen.findByLabelText("Coming up on Email");
      const time = document.getElementById("coming_up-time") as HTMLInputElement;
      expect(time.value).toBe("07:00");
      await user.clear(time);
      await user.type(time, "06:30");
      await user.tab();
      await waitFor(() =>
        expect(sent).toEqual([
          { digests: { coming_up: { cadence: "daily", at: "06:30", weekday: 1 } } },
        ])
      );
    });
  });

  describe("per community", () => {
    const serveCommunity = (muted: boolean) =>
      serve(
        buildNotificationPreferences({
          communities: [{ community_id: 4, community_name: "Acme", muted, off: ["subscriptions"] }],
        })
      );

    it("says which rows a community has off, switches one off there, and mutes it", async () => {
      const user = userEvent.setup();
      const sent = serveCommunity(false);
      renderPage();

      const mentions = await screen.findByLabelText("Mentions and replies in Acme");
      expect(mentions).toBeChecked();
      expect(screen.getByLabelText("Subscribed in Acme")).not.toBeChecked();
      // Closed, it says which of its rows are off.
      expect(screen.getByText("Off here: Subscribed")).toBeInTheDocument();
      // Only the rows about a community's content are per community.
      expect(screen.queryByLabelText("Waiting on you in Acme")).not.toBeInTheDocument();

      await user.click(mentions);
      // Every switch waits while a write is under way.
      await waitFor(() => expect(screen.getByLabelText("Mute Acme")).toBeEnabled());
      await user.click(screen.getByLabelText("Mute Acme"));
      await waitFor(() =>
        expect(sent).toEqual([
          { rows: [{ community_id: 4, category: "mentions", enabled: false }] },
          { mutes: [{ community_id: 4, muted: true }] },
        ])
      );
    });

    it("says a muted community says nothing, in place of its rows", async () => {
      serveCommunity(true);
      renderPage();

      expect(await screen.findByLabelText("Mute Acme")).toBeChecked();
      expect(screen.getByText("Muted")).toBeInTheDocument();
      expect(screen.getByText(/This community says nothing at all/)).toBeInTheDocument();
      expect(screen.queryByLabelText("Mentions and replies in Acme")).not.toBeInTheDocument();
    });
  });
});
