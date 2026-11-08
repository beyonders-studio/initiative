import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildTask, buildTaskListResponse, resetFactories } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { createTestQueryClient, renderPage } from "@/__tests__/helpers/render";
import { FocusSummary } from "@/components/tasks/FocusSummary";
import {
  FOCUS_DEFAULTS,
  FOCUS_HORIZON_ANY,
  FOCUS_PREFERENCES_KEY,
  type FocusPreferences,
  useFocusSummary,
} from "@/hooks/useFocusSummary";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";

const ME_TASKS = "/api/v1/me/tasks";

const EMPTY = "Nothing needs your attention right now. Pin a task to keep it here.";

/** The pin query is the one addressing tasks by id; everything else is the rules. */
const isPinRequest = (conditions: unknown) =>
  Array.isArray(conditions) &&
  conditions.length > 0 &&
  (conditions[0] as { field?: string }).field === "id";

type Payloads = {
  rules?: ReturnType<typeof buildTaskListResponse>;
  pins?: ReturnType<typeof buildTaskListResponse>;
};

const captured: URLSearchParams[] = [];

/** The status a finished task carries; the same one on every fixture here. */
const DONE = {
  id: 9,
  project_id: 1,
  name: "Done",
  category: "done" as const,
  position: 3,
  is_default: false,
  color: "#34D399",
  icon: "circle-check",
};

/** The filter the section asked for, once it has asked at all. */
async function firstQuery() {
  await waitFor(() => expect(captured.length).toBeGreaterThan(0));
  return JSON.parse(captured[0].get("conditions") ?? "[]");
}

function mockMyTasks({ rules, pins }: Payloads) {
  server.use(
    http.get(ME_TASKS, ({ request }) => {
      const params = new URL(request.url).searchParams;
      captured.push(params);
      const conditions = JSON.parse(params.get("conditions") ?? "[]");
      return HttpResponse.json(
        isPinRequest(conditions)
          ? (pins ?? buildTaskListResponse([]))
          : (rules ?? buildTaskListResponse([]))
      );
    })
  );
}

/**
 * `stored` is the blob exactly as the preferences API would hand it back —
 * used to seed shapes the current defaults would otherwise paper over.
 */
function renderFocus(prefs: Partial<FocusPreferences> = {}, stored?: unknown) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(VIEW_PREFERENCES_QUERY_KEY, {
    items: { [FOCUS_PREFERENCES_KEY]: stored ?? { ...FOCUS_DEFAULTS, ...prefs } },
  });

  const changeTaskStatus = vi.fn().mockResolvedValue(undefined);
  const Harness = () => {
    const focus = useFocusSummary();
    return (
      <FocusSummary
        focus={focus}
        activeCommunityId={1}
        changeTaskStatus={changeTaskStatus}
        isUpdatingTask={() => false}
      />
    );
  };

  return { ...renderPage(Harness, { queryClient }), changeTaskStatus };
}

beforeEach(() => {
  resetFactories();
  captured.length = 0;
});

describe("FocusSummary", () => {
  it("lists work that needs doing and keeps today's completions visible", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "Fix the deploy script", due_date: "2026-08-10T09:00:00Z" }),
        buildTask({ id: 2, title: "Review the release notes", due_date: "2026-08-11T09:00:00Z" }),
        buildTask({
          id: 3,
          title: "Ship the migration",
          completed_at: "2026-08-10T08:00:00Z",
          task_status: DONE,
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Fix the deploy script")).toBeInTheDocument();
    expect(screen.getByText("Review the release notes")).toBeInTheDocument();

    // The completed one stays on the list rather than disappearing, and the
    // header counts it as progress.
    const completed = screen.getByText("Ship the migration");
    expect(completed).toBeInTheDocument();
    expect(completed).toHaveClass("text-muted-foreground");
    expect(completed).not.toHaveClass("line-through");
    expect(screen.getByText("1 of 3 done")).toBeInTheDocument();
  });

  it("asks each priority for its own window, plus today's completions, in one query", async () => {
    mockMyTasks({});
    renderFocus({
      horizons: { urgent: FOCUS_HORIZON_ANY, high: FOCUS_HORIZON_ANY, medium: 2, low: 0 },
    });

    const conditions = await firstQuery();

    expect(conditions).toHaveLength(1);
    expect(conditions[0].logic).toBe("or");

    const stillOpen = {
      field: "status_category",
      op: "in_",
      value: ["backlog", "todo", "in_progress"],
    };
    const [lowDue, lowStart, mediumDue, mediumStart, alwaysLeg, doneLeg] = conditions[0].conditions;

    // Per priority: due-soon OR started, as sibling AND legs. Two things ride
    // on this shape: an AND between the two dates would drop work carrying
    // only one of them, and a third level of nesting is rejected outright by
    // the API's group-depth cap.
    expect(lowDue.conditions).toEqual([
      stillOpen,
      { field: "priority", op: "in_", value: ["low"] },
      { field: "due_date", op: "lte", value: expect.any(String) },
    ]);
    expect(lowStart.conditions).toEqual([
      stillOpen,
      { field: "priority", op: "in_", value: ["low"] },
      { field: "start_date", op: "lte", value: expect.any(String) },
    ]);
    expect(mediumDue.conditions[1]).toEqual({
      field: "priority",
      op: "in_",
      value: ["medium"],
    });
    expect(mediumStart.conditions[2].field).toBe("start_date");

    // Priorities set to "any date" share one leg and carry no date test at
    // all — that is what keeps urgent work with a distant deadline on the list.
    expect(alwaysLeg.conditions).toEqual([
      stillOpen,
      { field: "priority", op: "in_", value: ["urgent", "high"] },
    ]);

    expect(doneLeg.conditions).toEqual([
      { field: "status_category", op: "in_", value: ["done"] },
      { field: "completed_at", op: "gte", value: expect.any(String) },
    ]);

    // Both dates are measured to the same edge of the window, so one slider
    // means one thing rather than two.
    expect(lowStart.conditions[2].value).toBe(lowDue.conditions[2].value);
    // A wider window reaches further out than a narrower one.
    expect(new Date(mediumDue.conditions[2].value).getTime()).toBeGreaterThan(
      new Date(lowDue.conditions[2].value).getTime()
    );

    // The list spans every community the user belongs to and answers only to its
    // own settings — it is not scoped by the community you happen to be viewing,
    // nor by the task table's filters.
    expect(captured[0].get("conditions")).not.toContain("community_id");
  });

  it("asks for backlog work too, not just what someone moved to To Do", async () => {
    // Backlog is the default status of a newly created task, so excluding it
    // empties the section on an ordinary install — overdue tasks included.
    mockMyTasks({});
    renderFocus();

    const conditions = await firstQuery();

    const openValues = conditions[0].conditions
      .flatMap((leg: { conditions: { field: string; value: unknown }[] }) => leg.conditions)
      .filter((c: { field: string }) => c.field === "status_category")
      .map((c: { value: unknown }) => c.value);

    for (const value of openValues) {
      expect(value).not.toEqual(["todo", "in_progress"]);
    }
    expect(openValues).toContainEqual(["backlog", "todo", "in_progress"]);
  });

  it("shows a started task that carries no due date", async () => {
    // The table below groups this as "Today" off its start date alone; the
    // section agrees rather than needing a deadline before it will look.
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 1,
          title: "Draft the launch post",
          start_date: "2026-08-10T09:00:00Z",
          due_date: null,
        }),
        buildTask({ id: 2, title: "Sign the contract", due_date: "2026-08-11T09:00:00Z" }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("Draft the launch post")).toBeInTheDocument();
    // Dated work still leads: a deadline outranks work that merely started.
    const titles = screen
      .getAllByRole("link")
      .map((link) => link.textContent)
      .filter((title) => title === "Draft the launch post" || title === "Sign the contract");
    expect(titles).toEqual(["Sign the contract", "Draft the launch post"]);
  });

  it("never nests condition groups deeper than the API accepts", async () => {
    mockMyTasks({});
    renderFocus();

    const conditions = await firstQuery();

    // How many groups deep the payload goes; leaves do not count. The API's
    // _MAX_GROUP_DEPTH of 3 permits two group levels and rejects the whole
    // query with a 400 at three.
    const groupDepth = (nodes: unknown[]): number =>
      Math.max(
        0,
        ...nodes.map((node) => {
          const group = node as { conditions?: unknown[] };
          return group.conditions ? 1 + groupDepth(group.conditions) : 0;
        })
      );

    expect(groupDepth(conditions)).toBeLessThanOrEqual(2);
  });

  it("holds a priority to overdue and today's work at the bottom of its range", async () => {
    mockMyTasks({});
    renderFocus({ horizons: { urgent: 0, high: 0, medium: 0, low: 0 } });

    const conditions = await firstQuery();

    // One shared window means one pair of legs, not one pair per priority.
    const [dueLeg, startLeg, doneLeg] = conditions[0].conditions;
    expect(conditions[0].conditions).toHaveLength(3);
    expect(dueLeg.conditions[1].value).toEqual(["urgent", "high", "medium", "low"]);
    expect(startLeg.conditions[2].field).toBe("start_date");
    expect(doneLeg.conditions[0].value).toEqual(["done"]);

    // The window still ends at tonight, so anything already overdue matches.
    const endOfToday = new Date();
    endOfToday.setHours(23, 59, 59, 999);
    expect(new Date(dueLeg.conditions[2].value).getTime()).toBe(endOfToday.getTime());
  });

  it("carries the old single-window settings over to the per-priority ones", async () => {
    // A blob written before the sliders still says what the user asked for:
    // "everything due within a week, plus urgent and high whenever they land".
    mockMyTasks({});
    renderFocus({}, { open: true, dueWithinDays: 7, includeHighPriority: true, pins: [] });

    const conditions = await firstQuery();
    const [dueLeg, startLeg, alwaysLeg] = conditions[0].conditions;

    expect(dueLeg.conditions[1].value).toEqual(["medium", "low"]);
    expect(startLeg.conditions[1].value).toEqual(["medium", "low"]);
    expect(alwaysLeg.conditions).toEqual([
      { field: "status_category", op: "in_", value: ["backlog", "todo", "in_progress"] },
      { field: "priority", op: "in_", value: ["urgent", "high"] },
    ]);

    const weekOut = new Date();
    weekOut.setDate(weekOut.getDate() + 7);
    weekOut.setHours(23, 59, 59, 999);
    expect(new Date(dueLeg.conditions[2].value).getTime()).toBe(weekOut.getTime());
  });

  it("narrows one priority's window from the settings without touching the others", async () => {
    mockMyTasks({});
    renderFocus({ horizons: { urgent: FOCUS_HORIZON_ANY, high: 7, medium: 2, low: 2 } });

    await userEvent.click(await screen.findByLabelText("Focus settings"));

    const high = await screen.findByRole("slider", { name: "High" });
    expect(high).toHaveAttribute("aria-valuenow", "7");

    high.focus();
    await userEvent.keyboard("{ArrowLeft}");

    await waitFor(() => expect(high).toHaveAttribute("aria-valuenow", "6"));
    // Its neighbours keep their own windows.
    expect(screen.getByRole("slider", { name: "Medium" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByRole("slider", { name: "Urgent" })).toHaveAttribute(
      "aria-valuenow",
      String(FOCUS_HORIZON_ANY)
    );

    await waitFor(() => {
      const latest = JSON.parse(captured.at(-1)?.get("conditions") ?? "[]");
      const priorities = latest[0].conditions.flatMap(
        (leg: { conditions: { field: string; value: unknown }[] }) =>
          leg.conditions.filter((c) => c.field === "priority").map((c) => c.value)
      );
      expect(priorities).toContainEqual(["high"]);
    });
  });

  it("shows every task that matches, with no cutoff", async () => {
    // A task either meets the rules and belongs here, or it does not. There is
    // no display cap: a shorter list comes from a tighter date window.
    mockMyTasks({
      rules: buildTaskListResponse(
        Array.from({ length: 12 }, (_, index) =>
          buildTask({
            id: index + 1,
            title: `Task ${index + 1}`,
            due_date: `2026-08-${10 + index}T09:00:00Z`,
          })
        )
      ),
    });

    renderFocus();

    expect(await screen.findByText("Task 1")).toBeInTheDocument();
    expect(screen.getByText("Task 12")).toBeInTheDocument();
    expect(screen.getByText("0 of 12 done")).toBeInTheDocument();
  });

  it("holds the day's total steady as work gets completed", async () => {
    // Completing something re-labels a task already on the list; it must never
    // pull another one in and grow the denominator underneath the user.
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "One", due_date: "2026-08-10T09:00:00Z" }),
        buildTask({ id: 2, title: "Two", due_date: "2026-08-11T09:00:00Z" }),
        buildTask({
          id: 3,
          title: "Three",
          due_date: "2026-08-12T09:00:00Z",
          completed_at: new Date().toISOString(),
          task_status: DONE,
        }),
      ]),
    });

    renderFocus();

    expect(await screen.findByText("1 of 3 done")).toBeInTheDocument();
    expect(screen.getByText("One")).toBeInTheDocument();
    expect(screen.getByText("Two")).toBeInTheDocument();
    expect(screen.getByText("Three")).toBeInTheDocument();
  });

  it("says so when the rules match more than one page", async () => {
    mockMyTasks({
      rules: {
        ...buildTaskListResponse([buildTask({ id: 1, title: "One" })]),
        total_count: 140,
      },
    });

    renderFocus();

    expect(
      await screen.findByText("Showing the first 1. Narrow the date window for a shorter list.")
    ).toBeInTheDocument();
  });

  it("keeps a pinned task even when it does not match the rules", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({ id: 42, community_id: 1, title: "Pinned far-future task" }),
      ]),
    });

    renderFocus({ pins: [{ community_id: 1, task_id: 42 }] });

    expect(await screen.findByText("Pinned far-future task")).toBeInTheDocument();
  });

  it("does not mistake a same-numbered task in another community for the pinned one", async () => {
    // /me/tasks filters run per community against a shared id space, so an
    // `id IN (…)` query returns task 7 from every community the user belongs to.
    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({ id: 7, community_id: 1, title: "Someone else's task 7" }),
        buildTask({ id: 7, community_id: 2, title: "The pinned task 7" }),
      ]),
    });

    renderFocus({ pins: [{ community_id: 2, task_id: 7 }] });

    expect(await screen.findByText("The pinned task 7")).toBeInTheDocument();
    expect(screen.queryByText("Someone else's task 7")).not.toBeInTheDocument();
  });

  it("checks a task off from the list", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({ id: 1, title: "Fix the deploy script", due_date: "2026-08-10T09:00:00Z" }),
      ]),
    });

    const { changeTaskStatus } = renderFocus();
    const checkbox = await screen.findByLabelText("Mark task as done");
    await userEvent.click(checkbox);

    expect(changeTaskStatus).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), "done");
  });

  it("reopens a task that was completed today", async () => {
    mockMyTasks({
      rules: buildTaskListResponse([
        buildTask({
          id: 3,
          title: "Ship the migration",
          completed_at: "2026-08-10T08:00:00Z",
          task_status: DONE,
        }),
      ]),
    });

    const { changeTaskStatus } = renderFocus();
    const checkbox = await screen.findByLabelText("Mark task as in progress");
    await userEvent.click(checkbox);

    expect(changeTaskStatus).toHaveBeenCalledWith(
      expect.objectContaining({ id: 3 }),
      "in_progress"
    );
  });

  it("only asks for completions since the start of today", async () => {
    mockMyTasks({});
    renderFocus();

    const conditions = await firstQuery();
    const doneLeg = conditions[0].conditions.at(-1);
    const since = new Date(
      doneLeg.conditions.find((c: { field: string }) => c.field === "completed_at").value
    );

    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    expect(since.getTime()).toBe(midnight.getTime());
  });

  // The pin query carries no date filter, so yesterday's finished work would
  // otherwise sit in "completed today" indefinitely.
  it.each([
    ["drops a pinned task that was finished on an earlier day", false],
    ["keeps a pinned task that was finished today", true],
  ])("%s", async (_label, today) => {
    const finishedAt = new Date();
    if (!today) finishedAt.setDate(finishedAt.getDate() - 1);
    const title = today ? "Finished today" : "Finished yesterday";

    mockMyTasks({
      rules: buildTaskListResponse([]),
      pins: buildTaskListResponse([
        buildTask({
          id: 55,
          community_id: 1,
          title,
          completed_at: finishedAt.toISOString(),
          task_status: DONE,
        }),
      ]),
    });

    renderFocus({ pins: [{ community_id: 1, task_id: 55 }] });

    if (today) {
      const finished = await screen.findByText(title);
      expect(finished).toHaveClass("text-muted-foreground");
      expect(finished).not.toHaveClass("line-through");
      expect(screen.getByText("1 of 1 done")).toBeInTheDocument();
    } else {
      expect(await screen.findByText(EMPTY)).toBeInTheDocument();
      expect(screen.queryByText(title)).not.toBeInTheDocument();
    }
  });

  it("invites the user to pin something when there is nothing to show", async () => {
    mockMyTasks({});
    renderFocus();

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
  });
});
