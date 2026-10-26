import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";

import { EnvelopeImportDialog } from "./EnvelopeImportDialog";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const initiative = buildInitiative({
  id: 7,
  name: "Target",
  can: {
    manage: false,
    moderate: false,
    roster: true,
    view: [],
    create: [Tool.queue, Tool.file, Tool.project, Tool.catalog],
  },
});

vi.mock("@/hooks/useInitiatives", () => ({
  useInitiatives: () => ({ data: [initiative] }),
  useInitiative: () => ({ data: initiative }),
}));

import { toast } from "@/lib/mascotToast";

function selectFile(contents: object) {
  const input = screen.getByLabelText(/export file/i) as HTMLInputElement;
  const file = new File([JSON.stringify(contents)], "export.json", {
    type: "application/json",
  });
  // jsdom doesn't run File.text() from a change event; stub it on the file.
  Object.defineProperty(file, "text", { value: () => Promise.resolve(JSON.stringify(contents)) });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("EnvelopeImportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("imports a matching envelope into the chosen initiative", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/imports/envelope", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { result: { entity_title: "Restored Queue", created: {}, unmatched_handles: [] } },
          { status: 201 }
        );
      })
    );

    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);

    selectFile({ type: "initiative-queue", name: "Restored Queue", schema_version: 1 });
    // A single creatable initiative is auto-selected; the Import button enables.
    const importBtn = await screen.findByRole("button", { name: /^import$/i });
    await waitFor(() => expect(importBtn).not.toBeDisabled());
    await userEvent.click(importBtn);

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      initiative_id: 7,
      envelope: { type: "initiative-queue" },
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Restored Queue"))
    );
  });

  it("refreshes the tool's list once the import lands", async () => {
    server.use(
      communityHttp.post("/imports/envelope", () =>
        HttpResponse.json(
          { result: { entity_title: "Restored Queue", created: {}, unmatched_handles: [] } },
          { status: 201 }
        )
      )
    );
    const listKey = ["/api/v1/c/1/queues/", { initiative_id: 7 }];
    queryClient.setQueryData(listKey, { items: [] });

    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);

    selectFile({ type: "initiative-queue", name: "Restored Queue", schema_version: 1 });
    const importBtn = await screen.findByRole("button", { name: /^import$/i });
    await waitFor(() => expect(importBtn).not.toBeDisabled());
    await userEvent.click(importBtn);

    await waitFor(() => expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true));
  });

  it("sends a zipped export as it is, saying which tool it is for", async () => {
    let sent: string | null = null;
    server.use(
      communityHttp.post("/imports/envelope/archive", async ({ request }) => {
        sent = await request.text();
        return HttpResponse.json(
          { result: { entity_title: "Barovia maps", created: {}, unmatched_handles: [] } },
          { status: 201 }
        );
      })
    );

    renderWithProviders(<EnvelopeImportDialog tool={Tool.catalog} open onOpenChange={() => {}} />);

    const input = screen.getByLabelText(/export file/i) as HTMLInputElement;
    const file = new File(["PK"], "barovia.zip", { type: "application/zip" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));

    expect(await screen.findByText(/zipped export/i)).toBeInTheDocument();
    const importBtn = screen.getByRole("button", { name: /^import$/i });
    await waitFor(() => expect(importBtn).not.toBeDisabled());
    await userEvent.click(importBtn);

    await waitFor(() => expect(sent).not.toBeNull());
    // Multipart: the zip itself, the initiative, and the tool it is for.
    expect(sent).toMatch(/name="file"/);
    expect(sent).toContain("initiative-catalog");
    expect(sent).toMatch(/name="initiative_id"\r?\n\r?\n7/);
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("Barovia maps"))
    );
  });

  it("asks who the file's people are when the server stages it, then confirms", async () => {
    // The envelope quotes somebody nobody here matched, so nothing is
    // imported yet: the server hands back a staged job and the question.
    const stagedJob = {
      id: 42,
      community_id: 1,
      created_by: 1,
      source: "initiative-project",
      params: {},
      plan: {
        people: [
          {
            handle: "stranger#4321",
            name: "Alice Chen",
            comment_count: 3,
            suggested_user_id: null,
          },
        ],
      },
      result: null,
      status: "staged",
      error: null,
      expires_at: null,
      created_at: "2026-09-20T00:00:00Z",
      updated_at: "2026-09-20T00:00:00Z",
    };
    let confirmed: Record<string, unknown> | null = null;
    server.use(
      communityHttp.post("/imports/envelope", () => HttpResponse.json(stagedJob, { status: 202 })),
      communityHttp.post("/imports/jobs/42/confirm", async ({ request }) => {
        confirmed = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...stagedJob, status: "queued" });
      })
    );

    renderWithProviders(<EnvelopeImportDialog tool={Tool.project} open onOpenChange={() => {}} />);

    selectFile({ type: "initiative-project", name: "Imported Board", schema_version: 1 });
    const importBtn = await screen.findByRole("button", { name: /^import$/i });
    await waitFor(() => expect(importBtn).not.toBeDisabled());
    await userEvent.click(importBtn);

    // The second step, with the person it could not place.
    expect(await screen.findByText("Alice Chen")).toBeInTheDocument();
    expect(screen.getByText("stranger#4321")).toBeInTheDocument();
    // Nothing has been imported, so nothing is reported as imported.
    expect(toast.success).not.toHaveBeenCalled();

    // Leaving the row blank is a real answer: confirm with an empty map.
    await userEvent.click(screen.getByRole("button", { name: /^import$/i }));
    await waitFor(() => expect(confirmed).not.toBeNull());
    expect(confirmed).toEqual({});
  });

  it("rejects a file whose type belongs to a different tool", async () => {
    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);
    selectFile({ type: "initiative-file", name: "Notes", schema_version: 1 });
    expect(await screen.findByText(/import it from that tool's page/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^import$/i })).toBeDisabled();
  });

  it("rejects a file that isn't an Initiative export", async () => {
    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);
    selectFile({ hello: "world" });
    expect(await screen.findByText(/isn't a recognized Initiative export/i)).toBeInTheDocument();
  });

  it("ignores a slow read of an earlier file when a newer one is picked", async () => {
    renderWithProviders(<EnvelopeImportDialog tool={Tool.queue} open onOpenChange={() => {}} />);
    const input = screen.getByLabelText(/export file/i) as HTMLInputElement;

    // First pick: a file whose read resolves LATER.
    const slow = new File(["{}"], "slow.json", { type: "application/json" });
    let releaseSlow: (v: string) => void = () => {};
    Object.defineProperty(slow, "text", {
      value: () =>
        new Promise<string>((resolve) => {
          releaseSlow = resolve;
        }),
    });
    Object.defineProperty(input, "files", { value: [slow], configurable: true });
    input.dispatchEvent(new Event("change", { bubbles: true }));

    // Second pick, mid-flight: a valid matching file that resolves immediately.
    selectFile({ type: "initiative-queue", name: "Good Queue", schema_version: 1 });
    await waitFor(() => expect(screen.getByText(/Good Queue/)).toBeInTheDocument());

    // The earlier read finishes last with a wrong-tool payload — it must NOT
    // overwrite the newer selection's accepted state.
    releaseSlow(JSON.stringify({ type: "initiative-file", name: "Stale" }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/import it from that tool's page/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^import$/i })).not.toBeDisabled();
  });
});
