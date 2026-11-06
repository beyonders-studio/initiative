import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildDataJob } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { DataJobRead } from "@/api/generated/initiativeAPI.schemas";

import { DataJobsTable } from "./DataJobsTable";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/exportDownload", () => ({
  downloadExportArtifact: vi.fn(),
}));

import { downloadExportArtifact } from "@/lib/exportDownload";

const now = new Date();
const iso = (offsetMs: number) => new Date(now.getTime() + offsetMs).toISOString();

const exportJob = (overrides: Partial<DataJobRead>) =>
  buildDataJob({
    source: "community",
    template_id: "data-table",
    format: "zip",
    status: "done",
    expires_at: iso(86_400_000),
    created_at: iso(-1000),
    ...overrides,
  });
const importJob = (overrides: Partial<DataJobRead>) =>
  buildDataJob({
    direction: "import",
    source: "backup",
    template_id: null,
    format: null,
    created_at: iso(-500),
    ...overrides,
  });

describe("DataJobsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists both directions with direction-specific actions", async () => {
    server.use(
      communityHttp.get("/data-jobs/", () =>
        HttpResponse.json([
          importJob({ id: 20, status: "queued", created_at: iso(0) }),
          exportJob({ id: 10, status: "done" }),
          importJob({ id: 21, status: "done", created_at: iso(-2000) }),
        ])
      )
    );

    renderWithProviders(<DataJobsTable />);

    // The placeholder table has rows of its own, so wait for the data proper.
    await screen.findByRole("button", { name: /download/i });
    const rows = screen.getAllByRole("row");
    // header + 3 data rows
    expect(rows).toHaveLength(4);
    // Direction badges (the column HEADER also says "Export"; badges are the
    // two Import rows plus one Export row).
    expect(screen.getAllByText("Import")).toHaveLength(2);

    // Export done → Download; import queued → Cancel; import done → View report.
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view report/i })).toBeInTheDocument();
  });

  it("re-downloads a finished export via the download helper", async () => {
    server.use(
      communityHttp.get("/data-jobs/", () =>
        HttpResponse.json([exportJob({ id: 10, status: "done" })])
      )
    );
    renderWithProviders(<DataJobsTable />);
    await userEvent.click(await screen.findByRole("button", { name: /download/i }));
    await waitFor(() => expect(downloadExportArtifact).toHaveBeenCalled());
  });

  it("cancels a staged/queued import", async () => {
    let cancelled = false;
    server.use(
      communityHttp.get("/data-jobs/", () =>
        HttpResponse.json([importJob({ id: 20, status: "staged" })])
      ),
      communityHttp.delete("/imports/jobs/:jobId", () => {
        cancelled = true;
        return HttpResponse.json({ ...importJob({ id: 20 }), status: "cancelled" });
      })
    );
    renderWithProviders(<DataJobsTable />);
    await userEvent.click(await screen.findByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(cancelled).toBe(true));
  });

  it("clamps a stale done export whose artifact has expired", async () => {
    server.use(
      communityHttp.get("/data-jobs/", () =>
        HttpResponse.json([exportJob({ id: 10, status: "done", expires_at: iso(-60_000) })])
      )
    );
    renderWithProviders(<DataJobsTable />);
    expect(await screen.findByText("Expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });
});
