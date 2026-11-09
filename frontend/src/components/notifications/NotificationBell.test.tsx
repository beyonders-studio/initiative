import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories/notification.factory";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { NotificationRead, NotificationType } from "@/api/generated/initiativeAPI.schemas";

import { NotificationBell } from "./NotificationBell";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
// The bell reads the push channel's state to decide whether it still needs a
// timer; the socket itself is exercised in useNotificationStream.test.tsx.
let streamConnected = false;
vi.mock("@/hooks/useNotificationStream", () => ({
  useNotificationStreamConnected: () => streamConnected,
}));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"

const mockInbox = (notifications: NotificationRead[]) => {
  server.use(
    http.get("/api/v1/notifications/", () =>
      HttpResponse.json({
        notifications,
        unread_count: notifications.filter((n) => !n.read_at).length,
      })
    ),
    http.post("/api/v1/notifications/:id/read", () => HttpResponse.json({}))
  );
};

describe("NotificationBell export notifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downloads the artifact when an export_ready notification is clicked", async () => {
    mockInbox([
      buildNotification({
        type: "export_ready" as NotificationType,
        data: { community_id: 1, export_job_id: 42, source: "tasks", format: "pdf" },
      }),
    ]);
    server.use(
      http.get(
        "/api/v1/c/1/exports/jobs/42/download",
        () =>
          new HttpResponse(PDF, {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          })
      )
    );
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    const item = await screen.findByText(/export is ready/i);
    await userEvent.click(item);

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-42.pdf");
  });

  it("renders a failed export notification without a download", async () => {
    mockInbox([
      buildNotification({
        type: "export_failed" as NotificationType,
        data: { community_id: 1, export_job_id: 43, source: "tasks", format: "pdf" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    const item = await screen.findByText(/export failed/i);
    await userEvent.click(item);

    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("renders import notifications with their own text, not the generic fallback", async () => {
    mockInbox([
      buildNotification({
        type: "import_ready" as NotificationType,
        data: { community_id: 1, import_job_id: 7, source: "backup" },
      }),
      buildNotification({
        id: 2,
        type: "import_failed" as NotificationType,
        data: { community_id: 1, import_job_id: 8, source: "initiative-wiki" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    // Each import type renders its own text, not the generic fallback — the
    // bug was both showing "You have a new notification".
    expect(await screen.findByText(/import finished/i)).toBeInTheDocument();
    expect(screen.getByText(/import failed/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
    // Imports navigate to the Data-tab report rather than downloading.
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("names the sender and counts a direct message, and never previews one", async () => {
    mockInbox([
      buildNotification({
        type: "direct_message" as NotificationType,
        // Everything a direct-message line carries. There is no body here and
        // no mechanism that could add one.
        data: { conversation_id: "conv-1", sender_id: 7, sender_name: "alex#1234", count: 3 },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    expect(await screen.findByText(/alex#1234 sent you 3 messages/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
  });

  it("names who posted and what, not the generic fallback", async () => {
    mockInbox([
      buildNotification({
        type: "post_published" as NotificationType,
        data: {
          community_id: 1,
          post_id: 12,
          post_name: "Doors open at seven",
          author_name: "alex#1234",
          author_id: 7,
        },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    expect(await screen.findByText(/alex#1234 posted Doors open at seven/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
  });

  it("says who knocked and how it was answered, not the generic fallback", async () => {
    mockInbox([
      buildNotification({
        type: "initiative_join_requested" as NotificationType,
        data: {
          community_id: 1,
          initiative_id: 5,
          initiative_name: "Apollo",
          requester_name: "Ada Lovelace",
          target_path: "/i/5/settings/members",
        },
      }),
      buildNotification({
        id: 2,
        type: "initiative_join_approved" as NotificationType,
        data: { community_id: 1, initiative_id: 5, initiative_name: "Apollo" },
      }),
      buildNotification({
        id: 3,
        type: "initiative_join_denied" as NotificationType,
        data: { community_id: 1, initiative_id: 6, initiative_name: "Vanguard" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));

    expect(await screen.findByText(/Ada Lovelace asked to join Apollo/i)).toBeInTheDocument();
    expect(screen.getByText(/request to join Apollo was approved/i)).toBeInTheDocument();
    expect(screen.getByText(/request to join Vanguard was declined/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
  });
});

describe("NotificationBell reading", () => {
  // Nothing to navigate to, so the click is only ever about the read state.
  const unreadNotice = () => buildNotification({ read_at: null });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("clears the count on the click, not on the answer", async () => {
    // The server is made to take its time; nothing on screen should wait for
    // it. Marking read is a statement about the reader, and the notification
    // is one you are navigating away from anyway.
    let release: (() => void) | undefined;
    const answered = new Promise<void>((resolve) => {
      release = resolve;
    });
    const notice = unreadNotice();
    server.use(
      http.get("/api/v1/notifications/", () =>
        HttpResponse.json({ notifications: [notice], unread_count: 1 })
      ),
      http.post("/api/v1/notifications/:id/read", async () => {
        await answered;
        return HttpResponse.json(notice);
      })
    );

    renderWithProviders(<NotificationBell />);
    await screen.findByRole("button", { name: /1 unread/i });

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    await userEvent.click(await screen.findByText(/was assigned to you/i));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /1 unread/i })).not.toBeInTheDocument()
    );
    release?.();
  });

  it("puts the count back if the server refuses the read", async () => {
    const notice = unreadNotice();
    server.use(
      http.get("/api/v1/notifications/", () =>
        HttpResponse.json({ notifications: [notice], unread_count: 1 })
      ),
      http.post("/api/v1/notifications/:id/read", () => new HttpResponse(null, { status: 500 }))
    );

    renderWithProviders(<NotificationBell />);
    await screen.findByRole("button", { name: /1 unread/i });

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    await userEvent.click(await screen.findByText(/was assigned to you/i));

    // The optimistic read gives way to what the server says rather than
    // standing: a refetch follows the refusal.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /1 unread/i })).toBeInTheDocument()
    );
  });
});

describe("NotificationBell polling fallback", () => {
  const countInboxRequests = () => {
    let requests = 0;
    server.use(
      http.get("/api/v1/notifications/", () => {
        requests += 1;
        return HttpResponse.json({ notifications: [], unread_count: 0 });
      })
    );
    return () => requests;
  };

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    streamConnected = false;
  });

  it("stops polling on the fast interval while the push channel is open", async () => {
    streamConnected = true;
    const requests = countInboxRequests();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(requests()).toBe(1));

    await vi.advanceTimersByTimeAsync(120_000);

    // The socket refetches this query itself; a 30s timer would only duplicate it.
    expect(requests()).toBe(1);
  });

  it("holds no timer at all while the push channel is open", async () => {
    streamConnected = true;
    const requests = countInboxRequests();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(requests()).toBe(1));

    await vi.advanceTimersByTimeAsync(601_000);

    // The channel reaches every worker, and says so when it has been quiet —
    // so there is nothing left for a timer to catch that it would not.
    expect(requests()).toBe(1);
  });

  it("keeps polling when the push channel cannot connect", async () => {
    streamConnected = false;
    const requests = countInboxRequests();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(requests()).toBe(1));

    await vi.advanceTimersByTimeAsync(31_000);

    // Losing the socket must not mean losing notifications.
    await waitFor(() => expect(requests()).toBeGreaterThan(1));
  });
});

describe("NotificationBell reaction notifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const openBell = async () => {
    renderWithProviders(<NotificationBell />);
    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
  };

  it("names the latest reactor and how many others joined them", async () => {
    mockInbox([
      buildNotification({
        type: "comment_reaction" as NotificationType,
        data: {
          community_id: 1,
          target_type: "comment",
          target_id: 7,
          target_path: "/go/task/3",
          context_title: "Ship the thing",
          count: 3,
          reactor_count: 2,
          reactor_ids: [2, 3],
          emoji: "🎉",
          reactor_name: "@carol",
          reactor_id: 3,
          reactions: [
            { id: 1, emoji: "👍", reactor_id: 2, reactor_name: "@bob" },
            { id: 2, emoji: "👍", reactor_id: 3, reactor_name: "@carol" },
            { id: 3, emoji: "🎉", reactor_id: 3, reactor_name: "@carol" },
          ],
        },
      }),
    ]);
    await openBell();

    // One line for the whole flurry: the newest reactor, the others as a
    // count, and every distinct emoji they used.
    expect(
      await screen.findByText(/@carol and 1 other reacted 👍🎉 to your comment on Ship the thing/i)
    ).toBeInTheDocument();
  });

  it("counts everyone the line rolled up, not just the reactions it kept", async () => {
    mockInbox([
      buildNotification({
        type: "comment_reaction" as NotificationType,
        data: {
          community_id: 1,
          target_type: "comment",
          target_id: 7,
          target_path: "/go/task/3",
          context_title: "Ship the thing",
          count: 40,
          reactor_count: 40,
          // The detail has rolled off; only the two most recent survive.
          reactions: [
            { id: 39, emoji: "👍", reactor_id: 39, reactor_name: "@u39" },
            { id: 40, emoji: "🎉", reactor_id: 40, reactor_name: "@u40" },
          ],
          emoji: "🎉",
          reactor_name: "@u40",
          reactor_id: 40,
        },
      }),
    ]);
    await openBell();

    expect(await screen.findByText(/@u40 and 39 others reacted/i)).toBeInTheDocument();
  });
});
