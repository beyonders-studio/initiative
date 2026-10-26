import { useEffect, useMemo } from "react";

import { getItem, setItem } from "@/lib/storage";

/**
 * When the reader last opened what ``key`` names (`activityLastVisitKey`),
 * read once as the page opens, then moved to now.
 */
export const useLastVisit = (key: string | null): string | null => {
  // Read again only for another key: moving it to now must not take the
  // marks off the entries this visit is showing.
  const lastVisit = useMemo(() => (key ? getItem(key) : null), [key]);
  useEffect(() => {
    if (key) void setItem(key, new Date().toISOString());
  }, [key]);
  return lastVisit;
};
