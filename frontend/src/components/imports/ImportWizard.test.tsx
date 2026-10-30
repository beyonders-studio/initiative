import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ImportWizard } from "./ImportWizard";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

// The wizard's first step reads the manifest from the local file; stub the
// peek so the test doesn't need a real zip.
vi.mock("@/lib/backupPeek", () => ({
  BackupPeekError: class extends Error {
    code: string;
    constructor(code: string) {
      super(code);
      this.code = code;
    }
  },
  peekBackupManifest: vi.fn(),
}));

import { peekBackupManifest } from "@/lib/backupPeek";

const MANIFEST = {
  type: "guild-backup",
  guild: { name: "Old Community" },
  app_version: "0.56.0",
  exported_at: "2026-07-15T00:00:00Z",
  initiatives: [{ id: 1, name: "Lore", tools: {} }],
  entries: [{ tool: "queue" }, { tool: "file" }],
  assets: [{ size_bytes: 2_500_000 }],
};

const STAGED_JOB = {
  id: 55,
  community_id: 1,
  created_by: 1,
  direction: "import",
  source: "backup",
  params: {},
  status: "staged",
  plan: {
    source_community_name: "Old Community",
    initiatives: [
      {
        source_id: 1,
        name: "Lore",
        proposed_name: "Lore (imported)",
        entry_counts: { queue: 1, file: 1 },
      },
    ],
    asset_count: 1,
    asset_bytes: 2_500_000,
    skipped: [],
    unknown_types: [],
  },
  result: null,
  error: null,
  expires_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

/** Answer "where is this coming from?" — the step before the file. */
async function chooseBackup() {
  await userEvent.click(screen.getByRole("button", { name: /initiative backup/i }));
}

function pickFile() {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  const file = new File([new Uint8Array([1, 2, 3])], "backup.zip", {
    type: "application/zip",
  });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ImportWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    (peekBackupManifest as ReturnType<typeof vi.fn>).mockResolvedValue(MANIFEST);
  });

  it("peeks locally, uploads, shows the server plan, confirms, and reports", async () => {
    let uploaded = false;
    let confirmed = false;
    let pollCount = 0;
    server.use(
      communityHttp.post("/imports/backup", () => {
        uploaded = true;
        return HttpResponse.json(STAGED_JOB, { status: 201 });
      }),
      communityHttp.post("/imports/jobs/:jobId/confirm", () => {
        confirmed = true;
        return HttpResponse.json({ ...STAGED_JOB, status: "queued" });
      }),
      communityHttp.get("/data-jobs/:jobId", () => {
        pollCount += 1;
        // First poll running, then done.
        if (pollCount < 2) {
          return HttpResponse.json({ ...STAGED_JOB, status: "running" });
        }
        return HttpResponse.json({
          ...STAGED_JOB,
          status: "done",
          result: {
            initiatives: [{ source_id: 1, initiative_id: 9, name: "Lore (imported)" }],
            per_tool: { queue: { created: 1, failed: 0, skipped: 0 } },
            entries: [],
            assets_restored: 1,
            assets_deduped: 0,
            unmatched_handles: [],
          },
        });
      })
    );

    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);

    await chooseBackup();
    pickFile();

    // Local peek preview — nothing uploaded yet.
    expect(await screen.findByText(/Backup of Old Community/i)).toBeInTheDocument();
    expect(screen.getByText(/2\.4 MB/)).toBeInTheDocument();
    expect(uploaded).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: /upload backup/i }));

    // The server's authoritative plan.
    expect(await screen.findByText(/Lore \(imported\)/i)).toBeInTheDocument();
    expect(uploaded).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: /start import/i }));
    await waitFor(() => expect(confirmed).toBe(true));

    // Polls to done → report.
    expect(await screen.findByText(/import finished/i, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(/1 initiative created/i)).toBeInTheDocument();
  });

  it("rejects a non-backup file at the peek step without uploading", async () => {
    const { BackupPeekError } = await import("@/lib/backupPeek");
    (peekBackupManifest as ReturnType<typeof vi.fn>).mockRejectedValue(
      new BackupPeekError("not_backup")
    );
    let uploaded = false;
    server.use(
      communityHttp.post("/imports/backup", () => {
        uploaded = true;
        return HttpResponse.json(STAGED_JOB, { status: 201 });
      })
    );

    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);
    await chooseBackup();
    pickFile();

    expect(await screen.findByText(/isn't a valid Initiative backup/i)).toBeInTheDocument();
    expect(uploaded).toBe(false);
    expect(screen.queryByRole("button", { name: /upload backup/i })).not.toBeInTheDocument();
  });

  it("reads an Atlassian site: the tile opens the connect step", async () => {
    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /^jira & confluence/i }));
    expect(await screen.findByLabelText(/site address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/api token/i)).toHaveAttribute("type", "password");
  });

  it("picks a Jira fetch back up when the wizard is opened again", async () => {
    // A fetch outlives the dialog; the job it started is remembered, and
    // reopening lands on its review once it has been staged.
    localStorage.setItem("imports:atlassian-job:1", "77");
    server.use(
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json({
          ...STAGED_JOB,
          id: 77,
          source: "atlassian",
          plan: { atlassian: { projects: 1, tasks: 9 }, people: [] },
        })
      )
    );
    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);
    // Read once the dialog has settled on the review: the step it resumes
    // on redraws as the staged job arrives.
    await waitFor(() => expect(screen.getByText(/9 tasks from 1 project/i)).toBeInTheDocument());
  });

  it("sends the properties unticked on the review with the confirm", async () => {
    localStorage.setItem("imports:atlassian-job:1", "77");
    let confirmBody: Record<string, unknown> | null = null;
    const staged = {
      ...STAGED_JOB,
      id: 77,
      source: "atlassian",
      plan: {
        atlassian: {
          projects: 1,
          tasks: 9,
          properties: [
            { name: "Priority", type: "select", issue_count: 9 },
            { name: "Jira key", type: "text", issue_count: 9 },
          ],
        },
        people: [],
      },
    };
    server.use(
      communityHttp.get("/data-jobs/:jobId", () => HttpResponse.json(staged)),
      communityHttp.post("/imports/jobs/:jobId/confirm", async ({ request }) => {
        confirmBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...staged, status: "queued" });
      })
    );
    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);

    await userEvent.click(await screen.findByRole("checkbox", { name: /priority/i }));
    await userEvent.click(screen.getByRole("button", { name: /start import/i }));

    await waitFor(() => expect(confirmBody).not.toBeNull());
    expect(confirmBody).toEqual({ exclude_properties: ["Priority"] });
  });

  it("picks a Confluence fetch back up and shows what the spaces hold", async () => {
    localStorage.setItem("imports:atlassian-job:1", "78");
    server.use(
      communityHttp.get("/data-jobs/:jobId", () =>
        HttpResponse.json({
          ...STAGED_JOB,
          id: 78,
          source: "atlassian",
          params: { confluence_spaces: ["DOCS"] },
          plan: {
            atlassian: {
              spaces: 1,
              pages: 12,
              page_attachments: 3,
              dropped_macros: [{ name: "toc", count: 2 }],
            },
            people: [],
          },
        })
      )
    );
    renderWithProviders(<ImportWizard open onOpenChange={() => {}} />);
    await waitFor(() => expect(screen.getByText(/12 pages from 1 spaces/i)).toBeInTheDocument());
    expect(screen.getByText(/3 attached files stay behind/i)).toBeInTheDocument();
    expect(screen.getByText(/left out: toc ×2/i)).toBeInTheDocument();
    // No properties to untick: a wiki carries none.
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
