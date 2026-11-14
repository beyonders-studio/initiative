import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { NotificationsPage } from "./NotificationsPage";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

describe("NotificationsPage", () => {
  it("files a line under its local day and downloads a finished export on click", async () => {
    const read = vi.fn();
    server.use(
      http.get("/api/v1/notifications/", () =>
        HttpResponse.json({
          notifications: [
            buildNotification({
              type: "export_ready",
              created_at: new Date().toISOString(),
              data: { community_id: 1, export_job_id: 42, source: "tasks", format: "pdf" },
            }),
          ],
          unread_count: 1,
          next_cursor: null,
        })
      ),
      http.post("/api/v1/notifications/:id/read", () => {
        read();
        return HttpResponse.json({});
      }),
      http.get(
        "/api/v1/c/1/exports/jobs/42/download",
        () => new HttpResponse(new Uint8Array([0x25, 0x50, 0x44, 0x46]), { status: 200 })
      )
    );
    renderWithProviders(<NotificationsPage />);

    expect(await screen.findByRole("heading", { name: "Today" })).toBeInTheDocument();
    await userEvent.click(screen.getByText(/export is ready/i));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-42.pdf");
    expect(read).toHaveBeenCalled();
  });
});
