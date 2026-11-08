import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { endOfDay, endOfMonth, format, startOfDay, startOfMonth } from "date-fns";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildTask,
  buildToolLayoutSet,
  communityCan,
  writerCan,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { keepViewPreferences } from "@/__tests__/helpers/viewPreferences";
import {
  ActorKind,
  type FilterCondition,
  type FilterGroup,
} from "@/api/generated/initiativeAPI.schemas";
import { CALENDAR_VIEW_MODE_KEY } from "@/components/calendar";
import { dateRangeParams } from "@/components/calendar/visibleRange";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { viewPreferencesQueryKey } from "@/lib/viewPreferences";

import { CalendarsView } from "./CalendarsPage";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));

const INITIATIVE_ID = 1;
const PROJECT_ID = 1;

/** A day comfortably inside the focus month, so it lands in every view. */
const inFocusMonth = (dayOffset: number) => {
  const d = startOfMonth(new Date());
  d.setDate(d.getDate() + dayOffset);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
};

/** A query client holding the reader's views, as the app has them on opening
 *  a page: the calendar `mode` an older release kept on the account, and what
 *  community 1 keeps. */
const withViews = (mode: string, community: Record<string, unknown> = {}) => {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { [CALENDAR_VIEW_MODE_KEY]: mode },
  });
  queryClient.setQueryData(viewPreferencesQueryKey(1), { items: { ...community } });
  return queryClient;
};

/**
 * Render the calendar in list view — the list renders a row per entry, so a
 * task either appears or it doesn't. The month grid collapses a busy day into
 * "+N more", which would hide the very thing these tests check for.
 */
function renderCalendars() {
  const queryClient = withViews("list");
  const Page = () => <CalendarsView fixedInitiativeId={INITIATIVE_ID} canCreate={false} />;
  return renderPage(Page, { queryClient });
}

/**
 * Capture every GET /calendar-entries/ and serve one union payload. The
 * aggregate returns events + all in-window tasks in a single request, so there
 * is no per-page walking to stub. The page also lists the initiative's real
 * calendars for its panel; serve an empty set unless a test provides one.
 */
function stubEntries(
  { events = [], tasks = [] }: { events?: unknown[]; tasks?: unknown[] },
  calendars: unknown[] = []
) {
  const requests: URLSearchParams[] = [];
  server.use(
    communityHttp.get("/calendar-entries/", ({ request }) => {
      requests.push(new URL(request.url).searchParams);
      return HttpResponse.json({ events, tasks });
    }),
    communityHttp.get("/calendars/", () =>
      HttpResponse.json({
        items: calendars,
        total_count: calendars.length,
        page: 1,
        page_size: 100,
        has_next: false,
      })
    )
  );
  return requests;
}

const parseConditions = (params: URLSearchParams) =>
  JSON.parse(params.get("conditions") ?? "[]") as (FilterCondition | FilterGroup)[];

const isGroup = (c: FilterCondition | FilterGroup): c is FilterGroup => "conditions" in c;

/**
 * Open Subscribe from the toolbar's "More actions" menu and return the
 * calendars its dialog offers a link for, by name.
 */
const subscribeFromMenu = async (user: ReturnType<typeof userEvent.setup>) => {
  server.use(http.get("/api/v1/me/api-keys", () => HttpResponse.json({ keys: [] })));
  await user.click(await screen.findByRole("button", { name: /more actions/i }));
  await user.click(await screen.findByRole("menuitem", { name: "Subscribe" }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findAllByRole("button", { name: "Get link" });
  return dialog;
};

/** Export sits in the toolbar's "More actions" menu. */
const exportFromMenu = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("button", { name: /more actions/i }));
  await user.click(await screen.findByRole("menuitem", { name: /^export/i }));
};

describe("CalendarsView calendar-entries query", () => {
  it("issues a single calendar-entries request windowed to the dates the view renders", async () => {
    const requests = stubEntries({ tasks: [] });

    renderCalendars();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));

    // The window bounds BOTH legs via start_after/start_before — the endpoint
    // windows events and tasks by these, so the date range isn't duplicated
    // inside `conditions`. List view shows the focus month exactly.
    const now = new Date();
    expect(requests[0].get("start_after")).toBe(startOfMonth(now).toISOString());
    expect(requests[0].get("start_before")).toBe(endOfMonth(now).toISOString());

    // `conditions` carries only the non-window filters (none selected here), so
    // it never contains a start_date/due_date group.
    const groups = parseConditions(requests[0]).filter(isGroup);
    expect(groups).toHaveLength(0);
  });

  it("says why a range could not be shown", async () => {
    stubEntries({});
    server.use(
      communityHttp.get("/calendar-entries/", () =>
        HttpResponse.json({ detail: "CALENDAR_WINDOW_TOO_FULL" }, { status: 422 })
      )
    );

    renderCalendars();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This range has too many repeating events to show at once. Pick a shorter range"
    );
  });

  it("renders every in-window task the aggregate returns", async () => {
    // The aggregate returns all in-window tasks in one payload; the page used to
    // walk paginated /tasks and silently drop anything past the hundredth.
    const tasks = Array.from({ length: 101 }, (_, i) =>
      buildTask({
        id: i + 1,
        title: i === 100 ? "Hundred and first task" : `Task ${i + 1}`,
        project_id: PROJECT_ID,
        due_date: inFocusMonth(i % 27),
      })
    );
    stubEntries({ tasks });

    renderCalendars();

    expect(await screen.findByText("Hundred and first task")).toBeInTheDocument();
    expect(screen.getByText("Task 1")).toBeInTheDocument();
  });

  it("lists a task toggle per project with in-window tasks and hides its tasks when toggled off", async () => {
    // The filters derive one toggle per project FROM the tasks payload — a
    // project with no task in the window gets no row.
    const requests = stubEntries({
      tasks: [
        buildTask({
          id: 1,
          title: "Apollo task",
          project_id: PROJECT_ID,
          project_name: "Apollo",
          due_date: inFocusMonth(3),
        }),
      ],
    });

    const user = userEvent.setup();
    renderCalendars();

    expect(await screen.findByText("Apollo task")).toBeInTheDocument();

    // Which tasks show is a filter: the projects' toggles sit in the panel.
    await user.click(screen.getByRole("button", { name: /^filters$/i }));
    // Named from the task, which carries its project's name.
    expect(await screen.findByRole("checkbox", { name: "Apollo" })).toBeInTheDocument();

    // Unchecking the project hides its tasks from the view, and says so.
    await user.click(screen.getByRole("checkbox", { name: "Apollo" }));
    await waitFor(() => expect(screen.queryByText("Apollo task")).toBeNull());
    expect(screen.getByRole("button", { name: /1 active/i })).toBeInTheDocument();

    // Switching tasks off stops asking for them at all.
    await user.click(screen.getByRole("checkbox", { name: "Apollo" }));
    expect(await screen.findByText("Apollo task")).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Tasks" }));
    await waitFor(() => expect(requests.at(-1)?.get("include_tasks")).toBe("false"));
    expect(screen.queryByText("Apollo task")).toBeNull();
  });

  it("heads the tab's toolbar with the calendar picker, under the initiative's own title", async () => {
    stubEntries({}, [
      {
        id: 3,
        name: "Team",
        description: null,
        color: "#6366f1",
        initiative_id: INITIATIVE_ID,
        community_id: 1,
        created_by: 1,
        created_by_kind: ActorKind.member,
        created_by_install: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        can: writerCan(),
        comments_enabled: true,
        archived_at: null,
        tags: [],
        grants: [],
      },
    ]);
    renderCalendars();

    const heading = await screen.findByRole("heading", { level: 2, name: /all calendars/i });
    expect(within(heading).getByRole("button", { name: /all calendars/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("fetches where the date range meets the month on screen, and exports the range", async () => {
    const calendar = {
      id: 3,
      name: "Team",
      description: null,
      color: "#6366f1",
      initiative_id: INITIATIVE_ID,
      community_id: 1,
      created_by: 1,
      created_by_kind: ActorKind.member,
      created_by_install: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      can: writerCan(),
      comments_enabled: true,
      archived_at: null,
      tags: [],
      grants: [],
    };
    const requests = stubEntries({}, [calendar]);
    const exports: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/exports/events", ({ request }) => {
        exports.push(new URL(request.url).searchParams);
        return new HttpResponse("BEGIN:VCALENDAR", {
          headers: { "Content-Type": "text/calendar" },
        });
      })
    );
    const user = userEvent.setup();
    renderCalendars();
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));

    // The 10th to the 20th of the month the list shows.
    const now = new Date();
    const from = new Date(now.getFullYear(), now.getMonth(), 10);
    const until = new Date(now.getFullYear(), now.getMonth(), 20);
    await user.click(screen.getByLabelText("Dates"));
    const picker = await screen.findByRole("dialog");
    for (const day of [from, until]) {
      await user.click(
        within(picker).getByRole("button", { name: new RegExp(format(day, "MMMM do, yyyy")) })
      );
    }
    await waitFor(() =>
      expect(requests.at(-1)?.get("start_before")).toBe(endOfDay(until).toISOString())
    );
    expect(requests.at(-1)?.get("start_after")).toBe(startOfDay(from).toISOString());

    // The export takes the range itself, not the window on screen.
    await user.keyboard("{Escape}");
    await exportFromMenu(user);
    await waitFor(() => expect(exports).toHaveLength(1));
    const range = dateRangeParams({ from, until });
    expect(exports[0].get("start_after")).toBe(range.start_after);
    expect(exports[0].get("start_before")).toBe(range.start_before);

    // A range that misses the month on screen has nothing to fetch.
    const fetched = requests.length;
    await user.click(screen.getByLabelText("Dates"));
    await user.click(await screen.findByRole("button", { name: "Last month" }));
    expect(requests).toHaveLength(fetched);
  });
});

describe("CalendarsView presets", () => {
  /** The initiative calendar's layouts, its list offering `presets`. */
  const withPresets = (presets: unknown[]) =>
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(
          buildToolLayoutSet({
            tool: "calendar",
            layouts: [
              {
                kind: "calendar",
                is_default: true,
                hidden: false,
                definition: { presets } as never,
                updated_at: "2026-10-01T12:00:00.000Z",
              },
            ],
          })
        )
      )
    );

  it("applies a preset the calendar offers to its filters, and names it in the URL", async () => {
    withPresets([{ name: "Urgent", slug: "urgent", filters: { priorities: ["urgent"] } }]);
    const requests = stubEntries({ tasks: [] });
    const { router } = renderCalendars();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /filters/i }));
    await user.click(await screen.findByRole("combobox", { name: /^presets$/i }));
    await user.click(await screen.findByRole("option", { name: "Urgent" }));

    await waitFor(() =>
      expect(parseConditions(requests.at(-1) as URLSearchParams)).toContainEqual({
        field: "priority",
        op: "in_",
        value: ["urgent"],
      })
    );
    expect((router.state.location.search as { preset?: string }).preset).toBe("urgent");
  });

  it("offers no preset picker while the calendar has no presets", async () => {
    server.use(
      communityHttp.get("/layouts/", () =>
        HttpResponse.json(buildToolLayoutSet({ tool: "calendar" }))
      )
    );
    const requests = stubEntries({ tasks: [] });
    renderCalendars();
    const user = userEvent.setup();

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    await user.click(await screen.findByRole("button", { name: /filters/i }));
    expect(screen.queryByRole("combobox", { name: /^presets$/i })).toBeNull();
  });
});

describe("CalendarsView subscribing on an initiative's tab", () => {
  it("offers a link for each of the initiative's calendars", async () => {
    const calendar = (id: number, name: string) => ({
      id,
      name,
      description: null,
      color: "#6366f1",
      initiative_id: INITIATIVE_ID,
      community_id: 1,
      created_by: 1,
      created_by_kind: ActorKind.member,
      created_by_install: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      can: writerCan(),
      comments_enabled: true,
      archived_at: null,
      tags: [],
      grants: [],
    });
    stubEntries({}, [calendar(7, "Rehearsals"), calendar(8, "Matches")]);
    const user = userEvent.setup();

    renderCalendars();
    const dialog = await subscribeFromMenu(user);

    expect(within(dialog).getByText("Rehearsals")).toBeInTheDocument();
    expect(within(dialog).getByText("Matches")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: "Get link" })).toHaveLength(2);
  });
});

describe("CalendarsView on a community calendar", () => {
  /** The calendar the plug-in mounts: community-level, so it belongs to no initiative. */
  const communityCalendar = {
    id: 42,
    name: "Community calendar",
    description: null,
    color: "#6366f1",
    initiative_id: null,
    community_id: 1,
    created_by: 1,
    created_by_kind: ActorKind.member,
    created_by_install: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    can: writerCan(),
    comments_enabled: true,
    archived_at: null,
    tags: [],
    properties: [],
    grants: [],
  };

  it("starts a new event at the clicked hour", async () => {
    server.use(
      communityHttp.get("/calendar-entries/", () => HttpResponse.json({ events: [], tasks: [] })),
      communityHttp.get("/calendars/:calendarId", () => HttpResponse.json(communityCalendar))
    );
    const queryClient = withViews("day");
    const { container } = renderPage(() => <CalendarsView soloCalendar={communityCalendar} />, {
      queryClient,
    });
    await waitFor(() => expect(container.querySelectorAll('[role="button"]')).toHaveLength(24));
    const afternoon = container.querySelectorAll('[role="button"]')[15];
    if (!afternoon) throw new Error("Missing afternoon slot");
    fireEvent.click(afternoon);
    const dialog = await screen.findByRole("dialog");
    const when = await within(dialog).findByRole("group", { name: /^when$/i });
    expect(within(when).getAllByRole("combobox")[0]).toHaveTextContent("3:00 PM");
  });

  it("asks for its own events only, and reads nothing initiative-shaped", async () => {
    const entries: URLSearchParams[] = [];
    const calendarList: string[] = [];
    server.use(
      communityHttp.get("/calendar-entries/", ({ request }) => {
        entries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ events: [], tasks: [] });
      }),
      communityHttp.get("/calendars/", ({ request }) => {
        calendarList.push(request.url);
        return HttpResponse.json({
          items: [],
          total_count: 0,
          page: 1,
          page_size: 100,
          has_next: false,
        });
      })
    );

    const queryClient = withViews("list");
    const Page = () => <CalendarsView soloCalendar={communityCalendar} />;
    renderPage(Page, { queryClient });

    await waitFor(() => expect(entries.length).toBeGreaterThan(0));

    // Titled with its name and a way to its settings; there is nothing to pick.
    expect(
      await screen.findByRole("heading", { level: 1, name: "Community calendar" })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();

    // Exactly this calendar, no task leg, and no initiative to narrow to.
    expect(entries[0].getAll("calendar_ids")).toEqual([String(communityCalendar.id)]);
    expect(entries[0].get("include_tasks")).toBe("false");
    expect(entries[0].get("initiative_id")).toBeNull();

    // The panel, the task-calendar rows and the filter bar are all initiative-
    // shaped, so the surface never lists the community's calendars.
    expect(calendarList).toEqual([]);

    // Subscribing offers this calendar alone.
    const dialog = await subscribeFromMenu(userEvent.setup());
    expect(
      within(dialog).getByRole("heading", { name: "Subscribe to Community calendar" })
    ).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: "Get link" })).toHaveLength(1);
  });
});

describe("CalendarsView on the calendar plug-in's own surface", () => {
  const communityCalendar = (id: number, name: string) => ({
    id,
    name,
    description: null,
    color: "#6366f1",
    initiative_id: null,
    community_id: 1,
    created_by: 1,
    created_by_kind: ActorKind.member,
    created_by_install: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    can: writerCan(),
    comments_enabled: true,
    archived_at: null,
    tags: [],
    grants: [],
  });

  /** Serve the community's calendars, recording what the page asked for. */
  function stubCommunityScope(
    calendars: ReturnType<typeof communityCalendar>[],
    events: unknown[] = []
  ) {
    const entries: URLSearchParams[] = [];
    const calendarList: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/calendar-entries/", ({ request }) => {
        entries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ events, tasks: [] });
      }),
      communityHttp.get("/calendars/", ({ request }) => {
        calendarList.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: calendars,
          total_count: calendars.length,
          page: 1,
          page_size: 200,
          has_next: false,
        });
      })
    );
    return { entries, calendarList };
  }

  // The community's own calendars are its admins' to add.
  /** What the server keeps of this reader's views of the community's lists,
   *  as they save them. */
  let kept: Record<string, unknown> = {};
  beforeEach(() => {
    kept = keepViewPreferences(1);
  });

  function renderCommunityScope(community = buildCommunity({ id: 1, role: "admin" })) {
    const queryClient = withViews("list", kept);
    return renderPage(() => <CalendarsView communityScope />, {
      queryClient,
      communities: { activeCommunityId: 1, activeCommunity: community, communities: [community] },
    });
  }

  it("asks for the community's own calendars and overlays all of them", async () => {
    const { entries, calendarList } = stubCommunityScope([
      communityCalendar(42, "Holidays"),
      communityCalendar(43, "Game nights"),
    ]);

    renderCommunityScope();

    await waitFor(() => expect(entries.length).toBeGreaterThan(0));

    // The list is asked for by scope, not inferred from an absent initiative —
    // otherwise it would answer with every initiative's calendars too.
    expect(calendarList[0].get("scope")).toBe("community");
    // The events are asked for by scope too, rather than by naming the
    // calendars: the list above is one page of them, and an event on a calendar
    // past the end of it would simply not be drawn.
    expect(entries[0].get("scope")).toBe("community");
    expect(entries[0].getAll("calendar_ids")).toEqual([]);
    expect(entries[0].get("include_tasks")).toBe("false");
    expect(entries[0].get("initiative_id")).toBeNull();
  });

  const midsummer = {
    id: 1,
    calendar_id: 42,
    community_id: 1,
    title: "Midsummer",
    description: null,
    start_at: inFocusMonth(3),
    end_at: inFocusMonth(3),
    all_day: true,
    attendee_previews: [],
    properties: [],
    tags: [],
    can: writerCan(),
  };

  it("offers a link for each of the community's own calendars", async () => {
    stubCommunityScope([communityCalendar(42, "Holidays"), communityCalendar(43, "Game nights")]);

    renderCommunityScope();
    const dialog = await subscribeFromMenu(userEvent.setup());

    expect(within(dialog).getByText("Holidays")).toBeInTheDocument();
    expect(within(dialog).getByText("Game nights")).toBeInTheDocument();
  });

  it("offers no Subscribe where the community does not take this member's keys", async () => {
    stubCommunityScope([communityCalendar(42, "Holidays")]);
    const user = userEvent.setup();

    renderCommunityScope(
      buildCommunity({ id: 1, role: "admin", can: communityCan("admin", { use_api: false }) })
    );
    await user.click(await screen.findByRole("button", { name: /more actions/i }));

    expect(await screen.findByRole("menu")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Subscribe" })).toBeNull();
  });

  it("lets a reader hide one of them, and keeps it hidden the next time", async () => {
    stubCommunityScope(
      [communityCalendar(42, "Holidays"), communityCalendar(43, "Game nights")],
      [midsummer]
    );

    const user = userEvent.setup();
    const { unmount } = renderCommunityScope();

    expect(await screen.findByText("Midsummer")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All calendars" }));
    await user.click(await screen.findByRole("checkbox", { name: "Holidays" }));
    await waitFor(() => expect(screen.queryByText("Midsummer")).toBeNull());

    // It is kept for the reader, wherever they open it next.
    unmount();
    await waitFor(() => expect(Object.keys(kept)).toContain("view:calendars"));
    renderCommunityScope();

    // One calendar left on: the title is its name, with its settings beside it.
    expect(await screen.findByRole("button", { name: "Game nights" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByText("Midsummer")).toBeNull();
  });

  it("exports every date of the calendars on screen, leaving out a hidden one", async () => {
    stubCommunityScope([communityCalendar(42, "Holidays"), communityCalendar(43, "Game nights")]);
    const exports: URLSearchParams[] = [];
    server.use(
      communityHttp.get("/exports/events", ({ request }) => {
        exports.push(new URL(request.url).searchParams);
        return new HttpResponse("BEGIN:VCALENDAR", {
          headers: { "Content-Type": "text/calendar" },
        });
      })
    );

    const user = userEvent.setup();
    renderCommunityScope();

    await exportFromMenu(user);
    await waitFor(() => expect(exports).toHaveLength(1));
    expect(exports[0].get("scope")).toBe("community");
    expect(exports[0].getAll("calendar_ids")).toEqual([]);
    expect(exports[0].get("start_after")).toBeNull();

    await user.click(screen.getByRole("button", { name: "All calendars" }));
    await user.click(await screen.findByRole("checkbox", { name: "Holidays" }));
    await user.keyboard("{Escape}");
    await exportFromMenu(user);
    await waitFor(() => expect(exports).toHaveLength(2));
    expect(exports[1].get("scope")).toBe("community");
    expect(exports[1].getAll("exclude_calendar_ids")).toEqual(["42"]);
  });

  it("titles the page with the picker and puts the way to add a calendar on it", async () => {
    stubCommunityScope([communityCalendar(42, "Holidays"), communityCalendar(43, "Game nights")]);

    renderCommunityScope();

    // The picker is the page's title: this surface has no other filter, so
    // there is no disclosure to open before reaching it.
    const title = await screen.findByRole("heading", { level: 1, name: "All calendars" });
    expect(within(title).getByRole("button", { name: "All calendars" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /filters/i })).toBeNull();
    // Adding a calendar is offered on a populated surface too, not only from
    // the empty state.
    expect(screen.getByRole("button", { name: /new calendar/i })).toBeInTheDocument();
  });

  it("says how many calendars are showing, and shows them all again from the top", async () => {
    stubCommunityScope([
      communityCalendar(42, "Holidays"),
      communityCalendar(43, "Game nights"),
      communityCalendar(44, "Birthdays"),
    ]);

    const user = userEvent.setup();
    renderCommunityScope();

    await user.click(await screen.findByRole("button", { name: "All calendars" }));
    await user.click(await screen.findByRole("checkbox", { name: "Holidays" }));
    expect(await screen.findByRole("button", { name: "2 calendars" })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "All calendars" }));
    expect(screen.getByRole("checkbox", { name: "Holidays" })).toBeChecked();
    expect(screen.getByRole("button", { name: "All calendars" })).toBeInTheDocument();
  });

  it("offers to make the first one rather than showing an empty grid", async () => {
    stubCommunityScope([]);

    renderCommunityScope();

    expect(await screen.findByText(/no calendars yet/i)).toBeInTheDocument();
    // An admin adds one here without holding an initiative role.
    expect(screen.getAllByRole("button", { name: /new calendar/i }).length).toBeGreaterThan(0);
  });
});
