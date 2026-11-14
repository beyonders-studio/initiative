import { formatDistance } from "date-fns";
import { memo, useMemo } from "react";

import { useTimeFormat } from "@/ui/host";
import { dateTimeFormat } from "@/ui/lib/intl";
import { hour12Option } from "@/ui/lib/timeFormat";
import { useDateLocale } from "@/ui/lib/useDateLocale";
import { useLiveClockValue } from "@/ui/lib/useRelativeTime";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/ui/tooltip";

type DateCellProps = {
  date: string | null | undefined;
  isPastVariant?: "primary" | "destructive";
  isDone?: boolean;
};

/**
 * Memoized date cell for tables. The relative label and its past-due
 * styling both refresh in place as time passes (via the shared clock in
 * `useLiveClockValue`) without a page reload, while the absolute tooltip date is
 * memoized since it never changes.
 */
export const DateCell = memo(({ date, isPastVariant, isDone }: DateCellProps) => {
  const dateLocale = useDateLocale();
  // Read so the memoized tooltip is rebuilt when the account changes clocks.
  const timeFormat = useTimeFormat();
  const time = useMemo(() => {
    if (!date) {
      return null;
    }
    const parsed = new Date(date).getTime();
    return Number.isNaN(parsed) ? null : parsed;
  }, [date]);

  // A single snapshot string encodes both the label and whether the date is in
  // the past, so the cell re-renders exactly when either changes (and never when
  // neither does). "1|2 minutes ago" → past, "0|in 3 days" → future.
  const snapshot = useLiveClockValue((now) => {
    if (time == null) {
      return null;
    }
    const relative = formatDistance(time, now, { addSuffix: true, locale: dateLocale });
    return `${time < now ? "1" : "0"}|${relative}`;
  });

  const formattedDate = useMemo(
    () =>
      time != null
        ? dateTimeFormat(dateLocale.code, {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
            hour12: hour12Option(),
          }).format(new Date(time))
        : null,
    [time, dateLocale, timeFormat]
  );

  if (snapshot == null) {
    return <span className="text-muted-foreground">—</span>;
  }

  const isPastDate = snapshot[0] === "1";
  const relativeDate = snapshot.slice(2);

  const className = (() => {
    if (!isPastDate || !isPastVariant) {
      return "min-w-30 text-muted-foreground";
    }
    // Past due and done = green (success)
    if (isPastVariant === "destructive" && isDone) {
      return "min-w-30 text-green-600 dark:text-green-400";
    }
    // Past due and not done = red (destructive)
    if (isPastVariant === "destructive") {
      return "min-w-30 text-destructive";
    }
    // Past start date = primary
    return "min-w-30 text-primary";
  })();

  return (
    <div className={className}>
      <Tooltip>
        <TooltipTrigger>{relativeDate}</TooltipTrigger>
        <TooltipContent>{formattedDate}</TooltipContent>
      </Tooltip>
    </div>
  );
});

DateCell.displayName = "DateCell";
