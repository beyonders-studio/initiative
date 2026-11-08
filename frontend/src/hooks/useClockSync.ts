import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { notifyClock, parseTimeFormat, parseWeekStart, writeClock } from "@/ui/host";

/**
 * Copies the signed-in account's clock and week start into the kit's host,
 * which the formatters and pickers read. Mounted once, at the root.
 */
export const useClockSync = (): void => {
  const { user } = useAuth();
  const timeFormat = parseTimeFormat(user?.time_format);
  const weekStart = parseWeekStart(user?.week_starts_on);

  // Written during the root's render, not in an effect. The formatters are
  // plain functions and most of their callers never subscribe, so a value
  // applied after the commit would leave the whole tree on the previous clock
  // until something unrelated re-rendered it — which is exactly what happens
  // on the first load, when the account arrives after the first paint. The
  // root renders before everything under it, so writing here puts every
  // timestamp in the same pass on the right clock. The write is idempotent,
  // which is what makes it safe to repeat.
  writeClock({ timeFormat, weekStart });

  // Subscribers are told after the commit, because telling them mid-render
  // would be asking other components to re-render while this one is rendering.
  // Keyed on the values rather than on whether the write changed anything:
  // a double-invoked render would report "unchanged" on its second pass and
  // nobody would ever hear about the first.
  useEffect(() => {
    notifyClock();
  }, [timeFormat, weekStart]);
};
