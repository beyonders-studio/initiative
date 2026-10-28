/**
 * An event's page, as its readers and the people who change it use it: every
 * field saved on its own, and a repeating event asked which dates a change is
 * for.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCalendarEvent,
  buildPropertySummary,
  buildToolLayoutSet,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { type CalendarEventRead, MetadataType } from "@/api/generated/initiativeAPI.schemas";
import { eventSaveOptions } from "@/hooks/useCalendarEvents";
import { toast } from "@/lib/mascotToast";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { EventDetailPage } from "./EventDetailPage";

const EVENT_ROUTE = "/c/$communityId/i/$initiativeId/calendars/$calendarId/events/$eventId";
const PARAMS = { communityId: "1", initiativeId: "1", calendarId: "1", eventId: "9" };

/** What each change sent, in order, without the zone every one carries. */
let sent: Record<string, unknown>[] = [];

/** Serves `event` as it stands, and each change as `answer` says. */
const serve = (
  event: CalendarEventRead,
  answer: (body: Record<string, unknown>) => Response | CalendarEventRead = (body) =>
    Object.assign(event, body)
) =>
  server.use(
    communityHttp.get("/calendar-events/:eventId", () => HttpResponse.json(event)),
    communityHttp.patch("/calendar-events/:eventId", async ({ request }) => {
      const { tz: _tz, ...body } = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      const answered = answer(body);
      return answered instanceof Response ? answered : HttpResponse.json(answered);
    })
  );

/** The description opens on its preview: turn to its field and write. */
const writeDescription = async (user: ReturnType<typeof userEvent.setup>, text: string) => {
  const field = await screen.findByRole("group", { name: /^description$/i });
  await user.click(within(field).getByRole("tab", { name: /^write$/i }));
  const editor = await screen.findByRole("textbox", { name: /^description$/i });
  await user.clear(editor);
  await user.type(editor, text);
};

const open = (search: Record<string, unknown> = {}) =>
  renderPage(EventDetailPage, {
    initialRoute: EVENT_ROUTE,
    routeParams: PARAMS,
    routerSearch: search,
  });

beforeEach(() => {
  sent = [];
});

describe("an event's page", () => {
  it("keeps an imported quarter-hour start and seconds when editing only the end", async () => {
    const start = new Date("2026-07-01T09:15:27.123").toISOString();
    serve(
      buildCalendarEvent({
        id: 9,
        title: "Imported event",
        start_at: start,
        end_at: new Date("2026-07-01T10:15:00").toISOString(),
      })
    );
    open();
    const user = userEvent.setup();
    const when = await screen.findByRole("group", { name: /^when$/i });
    const selectors = within(when).getAllByRole("combobox");
    const endTime = selectors[1];
    if (!endTime) throw new Error("Missing end time selector");
    await user.click(endTime);
    await user.click(await screen.findByRole("option", { name: "11:00 AM" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      start_at: start,
      end_at: new Date("2026-07-01T11:00:00").toISOString(),
    });
  });

  it("retains the second occurrence of a repeated hour when editing the end", async () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const start = "2026-10-25T01:30:27.123Z";
    serve(
      buildCalendarEvent({
        id: 9,
        title: "Fold event",
        start_at: start,
        end_at: "2026-10-25T02:30:00Z",
      })
    );
    open();
    const user = userEvent.setup();
    const when = await screen.findByRole("group", { name: /^when$/i });
    const endTime = within(when).getAllByRole("combobox")[1];
    if (!endTime) throw new Error("Missing end time selector");
    await user.click(endTime);
    await user.click(await screen.findByRole("option", { name: "4:00 AM" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ start_at: start, end_at: "2026-10-25T03:00:00.000Z" });
  });

  it("saves a field on its own, and only that field", async () => {
    serve(buildCalendarEvent({ id: 9, title: "Standup", location: "Room 2" }));
    open();
    const user = userEvent.setup();

    const title = await screen.findByDisplayValue("Standup");
    await user.clear(title);
    await user.type(title, "Retro{Enter}");

    await waitFor(() => expect(sent).toEqual([{ title: "Retro" }]));
    expect(screen.getByDisplayValue("Room 2")).toBeInTheDocument();
  });

  it("lays itself out as its initiative's calendar does", async () => {
    serve(buildCalendarEvent({ id: 9, title: "Standup", location: "Room 2" }));
    server.use(
      communityHttp.get("/layouts/", ({ request }) => {
        const target = new URL(request.url).searchParams;
        expect([target.get("tool"), target.get("initiative_id")]).toEqual(["calendar", "1"]);
        return HttpResponse.json(
          buildToolLayoutSet({
            tool: "calendar",
            layouts: [
              {
                kind: "calendar_event",
                task_type_id: null,
                task_type_name: null,
                definition: {
                  header: [{ type: "field", props: { field: "title" } }],
                  main: [],
                  side: [],
                },
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        );
      })
    );
    open();

    // What the layout places nowhere is not on the page.
    expect(await screen.findByDisplayValue("Standup")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Room 2")).not.toBeInTheDocument();
  });

  it("shows a reader who cannot change it the event, and nothing to change it with", async () => {
    serve(
      buildCalendarEvent({
        id: 9,
        title: "Standup",
        description: "Bring the numbers",
        location: "Room 2",
        can: { edit: false },
      })
    );
    open();

    expect(await screen.findByText("Bring the numbers")).toBeInTheDocument();
    expect(screen.getByText("Room 2")).toBeInTheDocument();
    // The page shows it, and no box to change it in.
    expect(screen.getByRole("heading", { level: 1, name: "Standup" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /more actions/i })).not.toBeInTheDocument();
  });

  it("shows a plug-in's values and runs its actions where it is placed", async () => {
    const ran = vi.fn();
    const on = ["calendar_event"];
    server.use(
      communityHttp.get("/plugins/", () =>
        HttpResponse.json({
          items: [
            {
              id: 3,
              name: "CI",
              enabled: true,
              definition: {
                fields: [
                  { key: "ci.state", name: { en: "CI" }, kind: "badge", on },
                  { key: "ci.url", name: { en: "Build" }, kind: "link", on },
                  { key: "task.only", name: { en: "Tasks" }, kind: "text", on: ["task"] },
                ],
                parts: [
                  {
                    id: "builds",
                    name: { en: "Builds" },
                    on,
                    tree: {
                      type: "section",
                      children: [{ type: "field", props: { field: "ci.url" } }],
                    },
                  },
                ],
                actions: [{ id: "rerun", name: { en: "Run again" }, on, menu: true }],
              },
              item_initiatives: [1],
              item_fields: ["ci.state", "ci.url", "task.only"],
              item_parts: ["builds"],
              item_actions: ["rerun"],
            },
          ],
        })
      ),
      communityHttp.post("/plugins/3/actions/rerun", async ({ request }) => {
        ran(await request.json());
        return HttpResponse.json({ values: {} });
      })
    );
    serve(
      buildCalendarEvent({
        id: 9,
        title: "Standup",
        can: { edit: false },
        properties: [
          buildPropertySummary({ install_id: 3, key: "ci.state", value: { text: "passing" } }),
          buildPropertySummary({
            install_id: 3,
            key: "ci.url",
            value: { url: "https://ci.example/9", text: "#9" },
          }),
          buildPropertySummary({ install_id: 3, key: "task.only", value: "nope" }),
        ],
      })
    );
    open();

    // Its fields and its part show without being placed; the link its part
    // shows is drawn once, and a field for tasks not at all.
    expect(await screen.findByText("passing")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /#9/ })).toHaveLength(1);
    expect(screen.queryByText("nope")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /more actions/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Run again" }));
    await waitFor(() =>
      expect(ran).toHaveBeenCalledWith({ entity_type: "calendar_event", entity_id: 9 })
    );
  });

  it("asks which dates of a repeating event a change is for, and opens the date made its own", async () => {
    const series = buildCalendarEvent({
      id: 9,
      location: "Room 2",
      recurrence: "RRULE:FREQ=WEEKLY",
    });
    serve(series, (body) => ({ ...series, ...body, id: 42, series_id: 9, recurrence: null }));
    const { router } = open({ occurrence: "2026-10-27T15:00:00.000Z" });
    const user = userEvent.setup();

    const location = await screen.findByDisplayValue("Room 2");
    await user.clear(location);
    await user.type(location, "Room 3{Enter}");
    expect(await screen.findByText("Change a repeating event")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(sent).toEqual([
        { location: "Room 3", scope: "this", occurrence: "2026-10-27T15:00:00.000Z" },
      ])
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/c/1/i/1/calendars/1/events/42")
    );
  });

  it("refuses a description written over one since changed, and can overwrite it", async () => {
    const event = buildCalendarEvent({ id: 9, description: "Old" });
    serve(event, (body) => {
      if (body.description_base === "Old") {
        // Someone else's change landed first.
        event.description = "Theirs";
        return HttpResponse.json({ detail: "DESCRIPTION_CHANGED" }, { status: 409 });
      }
      return Object.assign(event, { description: body.description });
    });
    open();
    const user = userEvent.setup();

    await writeDescription(user, "Mine");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    const conflict = await screen.findByRole("alert");
    expect(await within(conflict).findByText("Theirs")).toBeInTheDocument();
    await user.click(within(conflict).getByRole("button", { name: /overwrite/i }));

    await waitFor(() =>
      expect(sent).toEqual([
        { description: "Mine", description_base: "Old" },
        { description: "Mine", description_base: "Theirs" },
      ])
    );
  });

  it("writes a description over the one the typing began from, not one landed meanwhile", async () => {
    const event = buildCalendarEvent({ id: 9, description: "Old" });
    serve(event, (body) =>
      body.description_base === event.description
        ? Object.assign(event, { description: body.description })
        : HttpResponse.json({ detail: "DESCRIPTION_CHANGED" }, { status: 409 })
    );
    const { queryClient } = open();
    const user = userEvent.setup();

    await writeDescription(user, "Mine");
    // Someone else's description lands while this one is being typed.
    event.description = "Theirs";
    await queryClient.invalidateQueries();
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(sent).toEqual([{ description: "Mine", description_base: "Old" }]));
    expect(await screen.findByRole("button", { name: /overwrite/i })).toBeInTheDocument();
  });

  it("undoes a cleared location for the dates it was cleared for", async () => {
    const series = buildCalendarEvent({
      id: 9,
      location: "Room 2",
      recurrence: "RRULE:FREQ=WEEKLY",
    });
    serve(series, (body) => ({ ...series, ...body }));
    open({ occurrence: "2026-10-27T15:00:00.000Z" });
    const user = userEvent.setup();

    await user.clear(await screen.findByDisplayValue("Room 2"));
    await user.keyboard("{Enter}");
    await user.click(await screen.findByLabelText("All events in the series"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled());
    const [, options] = vi.mocked(toast.success).mock.calls.at(-1) ?? [];
    options?.action?.onClick(new MouseEvent("click"));

    const target = { scope: "all", occurrence: "2026-10-27T15:00:00.000Z" };
    await waitFor(() =>
      expect(sent).toEqual([
        { location: null, ...target },
        { location: "Room 2", ...target },
      ])
    );
  });

  it("shows a reader a property's value as it reads elsewhere, a link opening", async () => {
    serve(
      buildCalendarEvent({
        id: 9,
        can: { edit: false },
        properties: [
          buildPropertySummary({
            name: "Agenda",
            type: MetadataType.url,
            value: "https://example.com/agenda",
          }),
        ],
      })
    );
    open();

    expect(await screen.findByRole("link", { name: /example\.com\/agenda/ })).toHaveAttribute(
      "href",
      "https://example.com/agenda"
    );
  });

  it("saves a new repeat only when asked, never a rule picked on the way", async () => {
    const event = buildCalendarEvent({ id: 9, recurrence: "RRULE:FREQ=WEEKLY" });
    let reply = () => {};
    const replied = new Promise<void>((resolve) => {
      reply = resolve;
    });
    serve(event);
    server.use(
      communityHttp.patch("/calendar-events/:eventId", async ({ request }) => {
        const { tz: _tz, ...body } = (await request.json()) as Record<string, unknown>;
        sent.push(body);
        await replied;
        return HttpResponse.json(Object.assign(event, body));
      })
    );
    open();
    const user = userEvent.setup();

    // A number that cannot be emptied, set as a whole.
    const every = await screen.findByLabelText(/repeat every/i);
    fireEvent.change(every, { target: { value: "2" } });
    await user.tab();
    expect(sent).toEqual([]);
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(String(sent[0].recurrence)).toContain("INTERVAL=2");

    // Another rule picked while that one saves stays picked once it has.
    fireEvent.change(every, { target: { value: "3" } });
    reply();
    await waitFor(() => expect(event.recurrence).toContain("INTERVAL=2"));
    await user.click(await screen.findByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(String(sent[1].recurrence)).toContain("INTERVAL=3");
  });
});

describe("a change to every date of a series", () => {
  const series = buildCalendarEvent({ id: 9, recurrence: "RRULE:FREQ=WEEKLY" });
  const target = (onShifted: (start: string) => void) => ({
    occurrence: "2026-10-27T15:00:00.000Z",
    occurrenceStart: "2026-10-27T15:00:00.000Z",
    askScope: async () => null,
    onMoved: vi.fn(),
    onShifted,
  });

  it("takes the page to the date shown, at its new time", () => {
    const onShifted = vi.fn();
    const moved = { start_at: "2026-10-27T16:00:00.000Z", end_at: "2026-10-27T17:00:00.000Z" };

    eventSaveOptions(series, target(onShifted)).onSaved?.({
      patch: { ...moved, scope: "all", occurrence: "2026-10-27T15:00:00.000Z" },
      shows: {},
    });
    eventSaveOptions(series, target(onShifted)).onSaved?.({
      patch: { location: "Room 3", scope: "all", occurrence: "2026-10-27T15:00:00.000Z" },
      shows: {},
    });

    expect(onShifted.mock.calls).toEqual([["2026-10-27T16:00:00.000Z"]]);
  });
});
