/**
 * What the initiative's calendar narrows its grid by: what its tasks are, and
 * the properties its events and tasks carry. The page keeps a person's own on
 * the device; a preset on the calendar's layout holds the same shape.
 */

import type { TaskPriority, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import type { PropertyFilterCondition } from "@/ui/properties/PropertyFilter";

export type CalendarFilters = {
  status_categories: TaskStatusCategory[];
  priorities: TaskPriority[];
  properties: PropertyFilterCondition[];
};

export const EMPTY_CALENDAR_FILTERS: CalendarFilters = {
  status_categories: [],
  priorities: [],
  properties: [],
};

const strings = <T extends string>(raw: unknown): T[] =>
  Array.isArray(raw) ? raw.filter((value): value is T => typeof value === "string") : [];

/** Coerce kept filters (every key optional) into the whole shape. */
export const calendarFiltersFromStored = (
  raw: Partial<Record<keyof CalendarFilters, unknown>> | null | undefined
): CalendarFilters => ({
  status_categories: strings<TaskStatusCategory>(raw?.status_categories),
  priorities: strings<TaskPriority>(raw?.priorities),
  properties: Array.isArray(raw?.properties)
    ? (raw.properties as PropertyFilterCondition[]).filter(
        (entry) => typeof entry?.property_id === "number"
      )
    : [],
});

/** The calendars, and the projects' tasks, a person has switched off on a
 *  calendar page, by `community:id` (a page may show several communities',
 *  whose ids collide), and whether they switched tasks off altogether. Kept
 *  as what is hidden, so a calendar or project that turns up later is shown. */
export type CalendarVisibility = {
  hiddenCalendarKeys: string[];
  hiddenProjectKeys: string[];
  hideTasks: boolean;
};

/** Everything a calendar page narrows by: its filters, the communities it
 *  shows (on a page that holds several), and what is switched off. */
export type CalendarViewFilters = CalendarFilters &
  CalendarVisibility & {
    community_ids: number[];
  };

export const EMPTY_CALENDAR_VIEW_FILTERS: CalendarViewFilters = {
  ...EMPTY_CALENDAR_FILTERS,
  community_ids: [],
  hiddenCalendarKeys: [],
  hiddenProjectKeys: [],
  hideTasks: false,
};

/** Coerce kept calendar page filters (every key optional) into the whole
 *  shape. */
export const calendarViewFiltersFromStored = (raw: unknown): CalendarViewFilters => {
  const kept = (raw !== null && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  return {
    ...calendarFiltersFromStored(kept),
    community_ids: Array.isArray(kept.community_ids)
      ? kept.community_ids.filter((id): id is number => typeof id === "number")
      : [],
    hiddenCalendarKeys: strings<string>(kept.hiddenCalendarKeys),
    hiddenProjectKeys: strings<string>(kept.hiddenProjectKeys),
    hideTasks: kept.hideTasks === true,
  };
};

const isRecord = (raw: unknown): raw is Record<string, unknown> =>
  raw !== null && typeof raw === "object" && !Array.isArray(raw);

/**
 * A calendar page's filters and mode as an older release kept them: `prefs`
 * (`statusFilters`, `priorityFilters`, `propertyFilters`, `communityFilters`,
 * and on My Calendar `calendarViewMode`), `visibility` (what was switched off)
 * and `mode`. Null where none of them holds anything.
 */
export const carriedCalendarView = (old: {
  prefs?: unknown;
  visibility?: unknown;
  mode?: unknown;
}): { mode: string | null; filters: Partial<CalendarViewFilters> } | null => {
  const prefs = isRecord(old.prefs) ? old.prefs : {};
  const hidden = isRecord(old.visibility) ? old.visibility : {};
  const filters = Object.fromEntries(
    Object.entries({
      status_categories: prefs.statusFilters,
      priorities: prefs.priorityFilters,
      properties: prefs.propertyFilters,
      community_ids: prefs.communityFilters,
      hiddenCalendarKeys: hidden.hiddenCalendarKeys,
      hiddenProjectKeys: hidden.hiddenProjectKeys,
      hideTasks: hidden.hideTasks,
    }).filter(([, value]) => value !== undefined)
  ) as Partial<CalendarViewFilters>;
  const mode =
    typeof old.mode === "string"
      ? old.mode
      : typeof prefs.calendarViewMode === "string"
        ? prefs.calendarViewMode
        : null;
  return Object.keys(filters).length > 0 || mode ? { mode, filters } : null;
};
