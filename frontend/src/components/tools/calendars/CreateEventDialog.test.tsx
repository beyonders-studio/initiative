import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildCalendarEvent, buildToolLayoutSet, writerCan } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { CreateEventDialog } from "./CreateEventDialog";

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

describe("adding an event", () => {
  it("retains the inferred end instant when the first hour ends in a fold", async () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const sent: string[] = [];
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
      communityHttp.post("/calendar-events/", async ({ request }) => {
        sent.push(await request.text());
        return HttpResponse.json(buildCalendarEvent({ id: 9, calendar_id: 7 }));
      })
    );
    renderPage(() => (
      <CreateEventDialog
        open
        onOpenChange={() => {}}
        defaultStartDate="2026-10-25"
        defaultStartTime="01:00"
      />
    ));
    const user = userEvent.setup();
    await user.type(await screen.findByPlaceholderText("Event title"), "Before the fold");
    await user.click(screen.getByRole("button", { name: "Create Event" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toContain('"start_at":"2026-10-24T23:00:00.000Z"');
    expect(sent[0]).toContain('"end_at":"2026-10-25T00:00:00.000Z"');
  });

  it("shows an invalid initial time instead of hiding the creation dialog", async () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    server.use(
      communityHttp.get("/calendars/", () =>
        HttpResponse.json({
          items: [CALENDAR],
          total_count: 1,
          page: 1,
          page_size: 200,
          has_next: false,
        })
      )
    );
    const close = vi.fn();
    renderPage(() => (
      <CreateEventDialog
        open
        onOpenChange={close}
        defaultStartDate="2026-10-25"
        defaultStartTime="02:00"
      />
    ));
    expect(await screen.findByRole("alert")).toHaveTextContent(/skipped or repeated/i);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(close).toHaveBeenCalledWith(false);
  });

  it("counts whoever is invited and the repeat it is sent with as filled in", async () => {
    const sent: Record<string, unknown>[] = [];
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
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            tool: "calendar",
            layouts: [
              {
                kind: "calendar_event",
                task_type_id: null,
                task_type_name: null,
                definition: {
                  side: [
                    { type: "field", props: { field: "attendees", required: true } },
                    { type: "field", props: { field: "recurrence", required: true } },
                  ],
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      ),
      communityHttp.post("/calendar-events/", async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(buildCalendarEvent({ id: 9, calendar_id: 7 }));
      })
    );
    renderPage(() => (
      <CreateEventDialog
        open
        onOpenChange={() => {}}
        defaultStartDate="2026-10-20"
        defaultStartTime="09:00"
      />
    ));
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText("Event title"), "Dress rehearsal");
    const add = screen.getByRole("button", { name: "Create Event" });
    // Whoever adds it is invited, which fills in who is coming.
    await waitFor(() =>
      expect(document.querySelector('[data-required-missing="recurrence"]')).not.toBeNull()
    );
    expect(document.querySelector('[data-required-missing="attendees"]')).toBeNull();
    expect(add).toBeDisabled();

    await user.click(screen.getByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Daily" }));
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ recurrence: expect.stringContaining("FREQ=DAILY") });
    expect(sent[0].attendee_ids).toHaveLength(1);
  });

  it.each(["09:00", "23:30"])(
    "starts at %s in the only calendar it can go in, and is made whole by Create",
    async (startTime) => {
      const sent: Record<string, unknown>[] = [];
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
        communityHttp.post("/calendar-events/", async ({ request }) => {
          const body = (await request.json()) as Record<string, unknown>;
          sent.push(body);
          return HttpResponse.json(buildCalendarEvent({ id: 9, calendar_id: 7 }));
        })
      );
      renderPage(() => (
        <CreateEventDialog
          open
          onOpenChange={() => {}}
          defaultStartDate="2026-10-20"
          defaultStartTime={startTime}
        />
      ));
      const user = userEvent.setup();

      expect(await screen.findByText("Rehearsals")).toBeInTheDocument();
      await user.type(screen.getByPlaceholderText("Event title"), "Dress rehearsal");
      await user.click(screen.getByRole("button", { name: "Create Event" }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(sent[0]).toMatchObject({
        calendar_id: 7,
        title: "Dress rehearsal",
        all_day: false,
        start_at: new Date(`2026-10-20T${startTime}:00`).toISOString(),
        end_at: new Date(
          new Date(`2026-10-20T${startTime}:00`).getTime() + 60 * 60_000
        ).toISOString(),
        properties: [],
      });
      expect(sent[0].attendee_ids).toHaveLength(1);
    }
  );
});
