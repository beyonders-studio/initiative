import { keepPreviousData } from "@tanstack/react-query";

import type {
  CalendarListResponse,
  ListMyCalendarsParams,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useListMyCalendars } from "@/api/generated/my-tools/my-tools";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import type { QueryOpts } from "@/types/query";

// ── The standard seven ──────────────────────────────────────────────────────
// Built in `toolHooks.ts` from the generated client; see there for the keys
// each one reads and the invalidation each one fires.

const calendars = TOOL_HOOKS[Tool.calendar];

export const useCalendarsList = calendars.useList;
export const useCalendar = calendars.useDetail;
export const useUpdateCalendar = calendars.useUpdate;
export const useDeleteCalendar = calendars.useDelete;
export const useSetCalendarGrants = calendars.useSetGrants;

// ── Queries ─────────────────────────────────────────────────────────────────

/** Cross-community variant for the My Calendar grouping panel — every calendar
 * visible to the user across their communities, in one request. */
export const useMyCalendars = (
  params?: ListMyCalendarsParams,
  options?: QueryOpts<CalendarListResponse>
) => {
  return useListMyCalendars(params, { query: { placeholderData: keepPreviousData, ...options } });
};
