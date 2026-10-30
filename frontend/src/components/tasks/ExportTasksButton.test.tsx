import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDataJob } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ExportTasksButton } from "./ExportTasksButton";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";
import { toast } from "@/lib/mascotToast";
import { getItem, setItem } from "@/lib/storage";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"

const pdfResponse = () =>
  new HttpResponse(PDF, { status: 200, headers: { "Content-Type": "application/pdf" } });

describe("ExportTasksButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("downloads the PDF directly on an inline (200) export", async () => {
    server.use(communityHttp.get("/exports/tasks", () => pdfResponse()));
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /pdf document/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks.pdf");
    expect(toast.success).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("polls a queued (202) job and downloads when it finishes", async () => {
    server.use(
      communityHttp.get("/exports/tasks", () =>
        HttpResponse.json(buildDataJob({ id: 7 }), { status: 202 })
      ),
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json(buildDataJob({ id: 7, status: "done" }))
      ),
      communityHttp.get("/exports/jobs/:jobId/download", () => pdfResponse())
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /pdf document/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-7.pdf");
  });

  it("surfaces a failed job as an error toast, without downloading", async () => {
    server.use(
      communityHttp.get("/exports/tasks", () =>
        HttpResponse.json(buildDataJob({ id: 7 }), { status: 202 })
      ),
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json(buildDataJob({ id: 7, status: "failed", error: "EXPORT_RENDER_FAILED" }))
      )
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /pdf document/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("sends the given selector and chosen format on the wire, honoring a label override", async () => {
    let sentConditions: unknown = null;
    let sentFormat: string | null = null;
    server.use(
      communityHttp.get("/exports/tasks", ({ request }) => {
        const url = new URL(request.url);
        const raw = url.searchParams.get("conditions");
        sentConditions = raw ? JSON.parse(raw) : null;
        sentFormat = url.searchParams.get("format");
        return pdfResponse();
      })
    );
    renderWithProviders(
      <ExportTasksButton
        params={{ conditions: [{ field: "id", op: "in_", value: [3, 5] }] }}
        label="Export Selected"
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Export Selected" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /csv/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sentConditions).toEqual([{ field: "id", op: "in_", value: [3, 5] }]);
    expect(sentFormat).toBe("csv");
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks.csv");
  });

  it("sends layout=checklist for the Markdown task list entry", async () => {
    let sent: { format: string | null; layout: string | null } | null = null;
    server.use(
      communityHttp.get("/exports/tasks", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          layout: url.searchParams.get("layout"),
        };
        return pdfResponse();
      })
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /task list/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual({ format: "md", layout: "checklist" });
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks.md");
  });

  it("sends format=pdf&layout=detailed for the detailed PDF entry", async () => {
    let sent: { format: string | null; layout: string | null } | null = null;
    server.use(
      communityHttp.get("/exports/tasks", ({ request }) => {
        const url = new URL(request.url);
        sent = {
          format: url.searchParams.get("format"),
          layout: url.searchParams.get("layout"),
        };
        return pdfResponse();
      })
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /pdf \(detailed\)/i }));

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(sent).toEqual({ format: "pdf", layout: "detailed" });
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks.pdf");
  });

  it("resumes a pending job from storage on mount and downloads it", async () => {
    setItem("exports:pending:1", "9");
    server.use(
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json(buildDataJob({ id: 9, status: "done" }))
      ),
      communityHttp.get("/exports/jobs/:jobId/download", () => pdfResponse())
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} resumePending />);

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-9.pdf");
    // The pending marker is consumed, so a remount won't re-download.
    expect(getItem("exports:pending:1")).toBeNull();
  });

  it("lets go of a stored pending id that names an import", async () => {
    setItem("exports:pending:1", "9");
    server.use(
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json(
          buildDataJob({ id: 9, direction: "import", source: "backup", status: "cancelled" })
        )
      )
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} resumePending />);

    await waitFor(() => expect(getItem("exports:pending:1")).toBeNull());
    expect(downloadBlob).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not adopt a stored pending job without resumePending", async () => {
    // Two instances share the community's pending key (toolbar + Export
    // Selected); only the designated adopter may resume, or a job in flight
    // when the second instance mounts would download twice.
    setItem("exports:pending:1", "9");
    const jobPoll = vi.fn(() => HttpResponse.json(buildDataJob({ id: 9, status: "done" })));
    server.use(communityHttp.get("/data-jobs/:jobId", jobPoll));
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(jobPoll).not.toHaveBeenCalled();
    expect(downloadBlob).not.toHaveBeenCalled();
    expect(getItem("exports:pending:1")).toBe("9");
  });

  it("shows a localized error for a rejected export (too large)", async () => {
    server.use(
      communityHttp.get("/exports/tasks", () =>
        HttpResponse.json({ detail: "EXPORT_TOO_LARGE" }, { status: 400 })
      )
    );
    renderWithProviders(<ExportTasksButton params={{ conditions: [] }} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /pdf document/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
