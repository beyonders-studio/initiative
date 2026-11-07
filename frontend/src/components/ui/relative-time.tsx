import { useMemo } from "react";

import { useDateLocale } from "@/hooks/useDateLocale";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { dateTimeFormat } from "@/lib/intl";
import { hour12Option } from "@/lib/timeFormat";
import { useTimeFormat } from "@/ui/host";

type RelativeTimeProps = {
  /** Timestamp to describe relative to now. */
  date: Date | string | number | null | undefined;
  /** Append/prepend "ago"/"in" (date-fns `addSuffix`). Defaults to `true`. */
  addSuffix?: boolean;
  /** Rendered when `date` is nullish or unparseable. */
  fallback?: React.ReactNode;
  className?: string;
  /**
   * Show the absolute date in a native tooltip on hover. Defaults to `true`.
   * Set `false` inside cells that provide their own richer tooltip.
   */
  showTitle?: boolean;
};

/**
 * A relative timestamp ("2 minutes ago") that refreshes in place as time passes,
 * without a page reload. Backed by the shared clock in `useRelativeTime`, so it
 * only re-renders when its displayed text changes. Drop-in replacement for
 * inline `formatDistanceToNow(...)` calls in tables and lists.
 */
export const RelativeTime = ({
  date,
  addSuffix = true,
  fallback = null,
  className,
  showTitle = true,
}: RelativeTimeProps) => {
  const locale = useDateLocale();
  const text = useRelativeTime(date, { addSuffix, locale });
  // Read so the memoized tooltip is rebuilt when the account changes clocks.
  const timeFormat = useTimeFormat();

  const title = useMemo(() => {
    if (!showTitle || date == null) {
      return undefined;
    }
    const parsed = typeof date === "object" ? date : new Date(date);
    return Number.isNaN(parsed.getTime())
      ? undefined
      : dateTimeFormat(locale.code, {
          weekday: "long",
          year: "numeric",
          month: "long",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
          hour12: hour12Option(),
        }).format(parsed);
  }, [showTitle, date, locale, timeFormat]);

  if (text == null) {
    return <>{fallback}</>;
  }

  return (
    <span className={className} title={title}>
      {text}
    </span>
  );
};
