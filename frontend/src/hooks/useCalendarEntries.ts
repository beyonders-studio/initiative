import { keepPreviousData } from "@tanstack/react-query";

import {
  useListCalendarEntries,
  useListMyCalendarEntries,
} from "@/api/generated/calendar-entries/calendar-entries";
import type {
  CalendarEntriesResponse,
  ListCalendarEntriesParams,
  ListMyCalendarEntriesParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { QueryOpts } from "@/types/query";

/**
 * One request for a community calendar's events + task markers over a window.
 * Replaces the paired `useCalendarEventsList` + `useTasks` calls the Events
 * page used to fire; the client still merges the union into calendar entries.
 */
export const useCalendarEntries = (
  params: ListCalendarEntriesParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  const communityId = useActiveCommunityId();
  return useListCalendarEntries(communityId, params, {
    query: { placeholderData: keepPreviousData, ...options },
  });
};

/**
 * Cross-community variant for the My Calendar page — the user's assigned task
 * markers + events across every community they belong to, in one request.
 */
export const useMyCalendarEntries = (
  params: ListMyCalendarEntriesParams,
  options?: QueryOpts<CalendarEntriesResponse>
) => {
  return useListMyCalendarEntries(params, {
    query: { placeholderData: keepPreviousData, ...options },
  });
};
