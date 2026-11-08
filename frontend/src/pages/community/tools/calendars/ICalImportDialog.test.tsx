/**
 * Importing an .ics file addresses the community it imports into.
 *
 * Every tooling request carries its community in the path
 * (`/api/v1/c/{communityId}/…`), and this dialog asked for the two import routes
 * without it, so the parse step reported an unreadable file for a perfectly
 * good calendar.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { writerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { ICalImportDialog } from "./ICalImportDialog";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const CALENDAR = {
  id: 7,
  name: "Rehearsals",
  description: null,
  color: "#336699",
  initiative_id: 3,
  community_id: 1,
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  can: writerCan(),
  comments_enabled: true,
  tags: [],
  grants: [],
};

const PARSED = {
  event_count: 2,
  has_recurring: false,
  events: [
    {
      summary: "Read-through",
      start_at: "2026-02-01T18:00:00Z",
      end_at: "2026-02-01T20:00:00Z",
      all_day: false,
      has_recurrence: false,
    },
    {
      summary: "Tech rehearsal",
      start_at: "2026-02-08T18:00:00Z",
      end_at: null,
      all_day: false,
      has_recurrence: false,
    },
  ],
};

const ICS = "BEGIN:VCALENDAR\nEND:VCALENDAR";

function pickFile() {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  const file = new File([ICS], "rehearsals.ics", { type: "text/calendar" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ICalImportDialog", () => {
  it("parses and imports through the community's own routes", async () => {
    const paths: string[] = [];
    server.use(
      communityHttp.get("/calendars/", () =>
        HttpResponse.json({
          items: [CALENDAR],
          total_count: 1,
          page: 1,
          page_size: 200,
          has_next: false,
        })
      ),
      communityHttp.post("/calendar-events/import/parse", ({ request }) => {
        paths.push(new URL(request.url).pathname);
        return HttpResponse.json(PARSED);
      }),
      communityHttp.post("/calendar-events/import", ({ request }) => {
        paths.push(new URL(request.url).pathname);
        return HttpResponse.json({
          events_created: 2,
          events_failed: 2,
          errors: [{ problem: "not_saved", title: "Dress rehearsal" }, { problem: "no_start" }],
        });
      })
    );

    renderWithProviders(<ICalImportDialog open onOpenChange={() => {}} />);

    pickFile();

    expect(await screen.findByText("Found 2 events")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "Rehearsals" }));
    await userEvent.click(screen.getByRole("button", { name: "Import Events" }));

    expect(await screen.findByText("Import complete!")).toBeInTheDocument();
    expect(screen.getByText("2 events created, 2 events failed")).toBeInTheDocument();
    // Each problem in the reader's language, naming the event it was about.
    expect(screen.getByText("Couldn't save “Dress rehearsal”")).toBeInTheDocument();
    expect(screen.getByText("Skipped “Untitled”: it has no start date")).toBeInTheDocument();
    expect(paths).toEqual([
      "/api/v1/c/1/calendar-events/import/parse",
      "/api/v1/c/1/calendar-events/import",
    ]);
  });
});
