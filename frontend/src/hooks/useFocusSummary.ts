import { keepPreviousData } from "@tanstack/react-query";
import { addDays, endOfDay, startOfDay } from "date-fns";
import { useCallback, useEffect, useMemo } from "react";

import type {
  FilterCondition,
  FilterGroup,
  ListMyTasksParams,
  TaskListRead,
  TaskPriority,
} from "@/api/generated/initiativeAPI.schemas";
import { useListMyTasks } from "@/api/generated/tasks/tasks";
import { useViewPreference } from "@/hooks/useViewPreference";
import { browserTimezone } from "@/lib/timezones";
import { useLiveClockValue } from "@/ui/lib/useRelativeTime";

/** A pinned task, addressed by community because task ids collide across communities. */
export type FocusPin = {
  community_id: number | null;
  task_id: number;
};

/** How far ahead the section looks, per priority. */
export type FocusHorizons = Record<TaskPriority, number>;

export type FocusPreferences = {
  /** Section expanded or collapsed. */
  open: boolean;
  /**
   * Days ahead to look, one window per priority: 0 keeps a priority to work
   * that is due today or overdue, and `FOCUS_HORIZON_ANY` drops the date test
   * altogether so the priority always appears.
   */
  horizons: FocusHorizons;
  pins: FocusPin[];
};

/** Highest first: the order the settings list them in. */
export const FOCUS_PRIORITIES = [
  "urgent",
  "high",
  "medium",
  "low",
] as const satisfies readonly TaskPriority[];

/** Top of the dated range — a month out is as far as "soon" stretches. */
export const FOCUS_HORIZON_MAX_DAYS = 30;

/**
 * One stop past the top of the range: match the priority whatever its dates
 * say. This is what keeps urgent work on the list when its deadline is months
 * away — the case a pure day window cannot express.
 */
export const FOCUS_HORIZON_ANY = FOCUS_HORIZON_MAX_DAYS + 1;

export const FOCUS_PREFERENCES_KEY = "my-tasks:focus";

export const FOCUS_DEFAULTS: FocusPreferences = {
  open: true,
  horizons: {
    urgent: FOCUS_HORIZON_ANY,
    high: FOCUS_HORIZON_ANY,
    medium: 2,
    low: 2,
  },
  pins: [],
};

/** The shape stored before the windows became per-priority. */
type LegacyFocusPreferences = {
  dueWithinDays?: unknown;
  includeHighPriority?: unknown;
};

const clampHorizon = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(FOCUS_HORIZON_ANY, Math.max(0, Math.round(value)))
    : fallback;

/**
 * Read the per-priority windows out of a stored blob, which may predate them
 * and is user-writable via the preferences API.
 *
 * A blob written by the old single-window settings still says what the user
 * asked for, so it is carried across rather than reset: its day count becomes
 * every priority's window, and its "always include urgent and high" switch
 * becomes `FOCUS_HORIZON_ANY` on those two.
 */
export function resolveHorizons(raw: unknown): FocusHorizons {
  const blob = (raw ?? {}) as { horizons?: unknown } & LegacyFocusPreferences;
  const stored = (blob.horizons ?? null) as Partial<Record<string, unknown>> | null;
  const legacyDays =
    stored === null && typeof blob.dueWithinDays === "number"
      ? clampHorizon(blob.dueWithinDays, FOCUS_DEFAULTS.horizons.medium)
      : null;
  const legacyAlwaysUrgent = blob.includeHighPriority !== false;

  return Object.fromEntries(
    FOCUS_PRIORITIES.map((priority) => {
      const fallback =
        legacyDays === null
          ? FOCUS_DEFAULTS.horizons[priority]
          : legacyAlwaysUrgent && (priority === "urgent" || priority === "high")
            ? FOCUS_HORIZON_ANY
            : legacyDays;
      return [priority, clampHorizon(stored?.[priority], fallback)];
    })
  ) as FocusHorizons;
}

/**
 * A stored blob read back as the current shape. Fields are picked out rather
 * than spread, so a legacy key is translated once and then dropped instead of
 * riding along in every later write.
 */
const normalizePreferences = (raw: unknown): FocusPreferences => {
  const blob = (raw ?? {}) as Partial<FocusPreferences>;
  return {
    open: typeof blob.open === "boolean" ? blob.open : FOCUS_DEFAULTS.open,
    horizons: resolveHorizons(raw),
    pins: Array.isArray(blob.pins) ? blob.pins : [],
  };
};

/**
 * Everything that is not finished. `backlog` belongs here as much as the other
 * two: it is the default status for a newly created task, so leaving it out
 * hides the bulk of most people's work — including tasks that are overdue.
 */
const OPEN_CATEGORIES = ["backlog", "todo", "in_progress"];
/**
 * The API's per-page maximum. There is deliberately no display cap on top of
 * it: a task either meets the rules and belongs on the list, or it does not.
 * Shortening an over-long list is the date window's job, not a hidden cutoff's.
 */
const FETCH_SIZE = 100;

const pinKey = (communityId: number | null | undefined, taskId: number) =>
  `${communityId ?? "none"}:${taskId}`;

/**
 * Conditions for the rule-driven half of the section: open work that has come
 * due (or already started) within its priority's window, plus anything
 * finished today so completions stay visible instead of vanishing the moment
 * they're checked off.
 *
 * Each window applies to `start_date` as well as `due_date`, matching how the
 * task table below groups by date (`getTaskDateStatus`): a task whose start
 * date has passed is work in hand even if nobody put a deadline on it.
 *
 * Priorities sharing a window share a leg, so the common case of two or three
 * distinct settings stays a short payload rather than one pair of legs per
 * priority.
 *
 * Exported for testing — the OR nesting is the part worth pinning down.
 */
export function buildFocusConditions({
  today,
  horizons,
  completedSince,
}: {
  /** Local midnight; each priority's window is measured forward from here. */
  today: Date;
  horizons: FocusHorizons;
  completedSince: Date;
}): FilterGroup[] {
  const stillOpen: FilterCondition = {
    field: "status_category",
    op: "in_",
    value: OPEN_CATEGORIES,
  };

  const byWindow = new Map<number, TaskPriority[]>();
  for (const priority of FOCUS_PRIORITIES) {
    const days = horizons[priority];
    byWindow.set(days, [...(byWindow.get(days) ?? []), priority]);
  }

  // "Open AND priority AND (due soon OR started)" is written out as sibling
  // AND legs rather than nesting an OR inside the AND: the API caps condition
  // nesting at two group levels and rejects a third outright. Distributing the
  // shared leaves costs a little duplication and keeps the same meaning.
  const legs: FilterGroup[] = [];
  for (const [days, priorities] of [...byWindow].sort(([a], [b]) => a - b)) {
    const atPriority: FilterCondition = { field: "priority", op: "in_", value: priorities };

    if (days >= FOCUS_HORIZON_ANY) {
      legs.push({ logic: "and", conditions: [stillOpen, atPriority] });
      continue;
    }

    const horizon = endOfDay(addDays(today, days)).toISOString();
    legs.push({
      logic: "and",
      conditions: [stillOpen, atPriority, { field: "due_date", op: "lte", value: horizon }],
    });
    legs.push({
      logic: "and",
      conditions: [stillOpen, atPriority, { field: "start_date", op: "lte", value: horizon }],
    });
  }

  legs.push({
    logic: "and",
    conditions: [
      { field: "status_category", op: "in_", value: ["done"] },
      { field: "completed_at", op: "gte", value: completedSince.toISOString() },
    ],
  });

  return [{ logic: "or", conditions: legs }];
}

/**
 * Whether a task's completion falls on or after `since` (local midnight).
 *
 * A done task with no timestamp predates the completed_at column, so it is
 * treated as finished earlier rather than credited to today.
 */
const completedOnOrAfter = (task: TaskListRead, since: number) =>
  task.completed_at != null && new Date(task.completed_at).getTime() >= since;

const byDueDate = (a: TaskListRead, b: TaskListRead) => {
  // Undated work sorts last: it has no clock pressure, so it should never
  // displace something with a deadline. Within that group, work that has
  // already started leads — it is in hand, whatever the table says about it.
  if (!a.due_date && !b.due_date) {
    if (a.start_date && b.start_date) {
      return a.start_date.localeCompare(b.start_date) || a.id - b.id;
    }
    if (a.start_date) return -1;
    if (b.start_date) return 1;
    return a.id - b.id;
  }
  if (!a.due_date) return 1;
  if (!b.due_date) return -1;
  return a.due_date.localeCompare(b.due_date);
};

/**
 * The reader's focus preferences and their pins, without the focus card's own
 * reads: for a list that marks pinned rows (the tasks table) and is shown
 * whether or not the card is.
 */
export function useFocusPreferences() {
  const [prefsRaw, setPrefs, { isLoaded }] = useViewPreference<FocusPreferences>(
    FOCUS_PREFERENCES_KEY,
    FOCUS_DEFAULTS
  );

  // A stored blob predates any later field, and is user-writable via the API.
  const prefs = useMemo<FocusPreferences>(() => normalizePreferences(prefsRaw), [prefsRaw]);

  const isPinned = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">) =>
      prefs.pins.some(
        (pin) => pinKey(pin.community_id, pin.task_id) === pinKey(task.community_id, task.id)
      ),
    [prefs.pins]
  );

  const togglePin = useCallback(
    (task: Pick<TaskListRead, "id" | "community_id">) => {
      const key = pinKey(task.community_id, task.id);
      setPrefs((prev) => {
        const current = normalizePreferences(prev);
        const without = current.pins.filter((pin) => pinKey(pin.community_id, pin.task_id) !== key);
        return {
          ...current,
          pins:
            without.length === current.pins.length
              ? [...current.pins, { community_id: task.community_id ?? null, task_id: task.id }]
              : without,
        };
      });
    },
    [setPrefs]
  );

  return { prefs, setPrefs, isLoaded, isPinned, togglePin };
}

/**
 * The "Focus summary" data: a small, capped set of work that needs doing now,
 * plus today's completions.
 *
 * Two queries rather than one, deliberately. Pins are addressed by
 * (community, task) but `/me/tasks` filters run per community against a shared id
 * space, so an `id IN (…)` leg matches same-numbered tasks in *other* communities
 * too; the pin query over-fetches and is narrowed here. Folding it into the
 * rule query would also push pinned-but-not-urgent work past the fetch window
 * whenever the rules match a lot.
 */
export function useFocusSummary() {
  const { prefs, setPrefs, isLoaded, isPinned, togglePin } = useFocusPreferences();

  const timezone = useMemo(browserTimezone, []);

  // Local midnight, off the shared clock: the list starts clean each morning,
  // so a tab left open overnight rolls over on its own instead of showing
  // yesterday's finished work. The value only changes when the day does, so it
  // costs no re-renders in between (and a fresh `new Date()` per render would
  // churn the query key continuously).
  const today = useLiveClockValue((now) => startOfDay(now).getTime());

  const ruleParams = useMemo<ListMyTasksParams>(
    () => ({
      conditions: buildFocusConditions({
        today: new Date(today),
        horizons: prefs.horizons,
        completedSince: new Date(today),
      }),
      page: 1,
      page_size: FETCH_SIZE,
      sorting: [{ field: "due_date", dir: "asc" }],
      tz: timezone,
    }),
    [today, prefs.horizons, timezone]
  );

  const ruleQuery = useListMyTasks(ruleParams, {
    query: { enabled: isLoaded, placeholderData: keepPreviousData },
  });

  const pinnedIds = useMemo(
    () => [...new Set(prefs.pins.map((pin) => pin.task_id))].sort((a, b) => a - b),
    [prefs.pins]
  );

  const pinParams = useMemo<ListMyTasksParams>(
    () => ({
      conditions: [{ field: "id", op: "in_", value: pinnedIds }],
      page: 1,
      page_size: FETCH_SIZE,
      tz: timezone,
    }),
    [pinnedIds, timezone]
  );

  const pinQuery = useListMyTasks(pinParams, {
    query: { enabled: isLoaded && pinnedIds.length > 0, placeholderData: keepPreviousData },
  });

  const setPreference = useCallback(
    <K extends keyof FocusPreferences>(key: K, value: FocusPreferences[K]) => {
      setPrefs((prev) => ({ ...normalizePreferences(prev), [key]: value }));
    },
    [setPrefs]
  );

  /**
   * Widen or narrow one priority's window. Written off `prev` rather than the
   * rendered value so dragging one slider never writes back a neighbour's
   * pre-drag setting.
   */
  const setHorizon = useCallback(
    (priority: TaskPriority, days: number) => {
      setPrefs((prev) => {
        const current = normalizePreferences(prev);
        return {
          ...current,
          horizons: {
            ...current.horizons,
            [priority]: clampHorizon(days, current.horizons[priority]),
          },
        };
      });
    },
    [setPrefs]
  );

  const derived = useMemo(() => {
    const ruleItems = ruleQuery.data?.items ?? [];
    const pinItems = (pinQuery.data?.items ?? []).filter((task) => isPinned(task));

    const seen = new Set<string>();
    const pinned: TaskListRead[] = [];
    for (const task of pinItems) {
      const key = pinKey(task.community_id, task.id);
      if (seen.has(key)) continue;
      seen.add(key);
      pinned.push(task);
    }

    const openMatches: TaskListRead[] = [];
    const completedToday: TaskListRead[] = [];
    for (const task of ruleItems) {
      const key = pinKey(task.community_id, task.id);
      if (task.task_status.category === "done") {
        if (seen.has(key)) continue;
        seen.add(key);
        completedToday.push(task);
        continue;
      }
      if (seen.has(key)) continue;
      seen.add(key);
      openMatches.push(task);
    }

    // A pinned task completed today belongs with the day's wins rather than the
    // list of things still to do. One completed on an earlier day is finished
    // business: the list starts clean each morning, so it drops off entirely
    // (the pin query carries no date filter of its own, unlike the rule query).
    const pinnedOpen = pinned.filter((task) => task.task_status.category !== "done");
    const pinnedDoneToday = pinned.filter(
      (task) => task.task_status.category === "done" && completedOnOrAfter(task, today)
    );
    const finishedEarlier = pinned.filter(
      (task) => task.task_status.category === "done" && !completedOnOrAfter(task, today)
    );

    openMatches.sort(byDueDate);

    return {
      pinned: pinnedOpen,
      upcoming: openMatches,
      completedToday: [...pinnedDoneToday, ...completedToday].sort(byDueDate),
      finishedEarlier,
      // The rules matched more than one page. Rare, and not something the
      // section decides — but say so rather than quietly showing a prefix.
      truncated: (ruleQuery.data?.total_count ?? 0) > ruleItems.length,
    };
  }, [ruleQuery.data, pinQuery.data, isPinned, today]);

  // Drop pins the user has already finished on an earlier day, so the blob
  // doesn't accumulate them and the pin query stays small. Only pins we
  // positively resolved are removed — an absent one may just be out of reach
  // for now, and forgetting it would silently lose the user's choice.
  const staleIds = derived.finishedEarlier
    .map((task) => pinKey(task.community_id, task.id))
    .join("|");
  useEffect(() => {
    if (!staleIds) return;
    const stale = new Set(staleIds.split("|"));
    setPrefs((prev) => {
      const current = normalizePreferences(prev);
      return {
        ...current,
        pins: current.pins.filter((pin) => !stale.has(pinKey(pin.community_id, pin.task_id))),
      };
    });
  }, [staleIds, setPrefs]);

  const remainingCount = derived.pinned.length + derived.upcoming.length;
  const doneCount = derived.completedToday.length;
  // `finishedEarlier` only feeds the pruning effect above; it is not part of
  // what the section renders.
  const { finishedEarlier: _finishedEarlier, ...visible } = derived;

  return {
    ...visible,
    prefs,
    setPreference,
    setHorizon,
    isPinned,
    togglePin,
    /** Everything on today's list, done or not — the progress denominator. */
    totalCount: remainingCount + doneCount,
    doneCount,
    isLoading: isLoaded && ruleQuery.isPending,
    hasError: ruleQuery.isError,
    isEmpty: remainingCount === 0 && doneCount === 0,
  };
}
