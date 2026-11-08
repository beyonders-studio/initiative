import {
  endOfDay,
  endOfMonth,
  endOfQuarter,
  endOfYear,
  startOfDay,
  startOfMonth,
  startOfQuarter,
  startOfYear,
  subMonths,
} from "date-fns";
import { Calendar as CalendarIcon, X } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Calendar } from "@/ui/calendar";
import { useFieldControl } from "@/ui/field";
import { fieldClass } from "@/ui/input";
import { dateTimeFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** A span of calendar days in the viewer's zone. Either end may be open. */
export interface LocalDateRange {
  from?: Date;
  until?: Date;
}

export const isDateRangeSet = (range: LocalDateRange): boolean =>
  range.from != null || range.until != null;

/** The instants a range covers: the start of its first day and the end of its
 *  last, in the viewer's zone. An open end stays undefined. */
export const dateRangeBounds = ({ from, until }: LocalDateRange): { start?: Date; end?: Date } => ({
  start: from ? startOfDay(from) : undefined,
  end: until ? endOfDay(until) : undefined,
});

const dayFormat = () => dateTimeFormat(undefined, { dateStyle: "medium" });

/** Reads a range out loud: "Jul 1 – Sep 30, 2026", "From Jul 1, 2026", or
 *  "" when neither end is set. */
export const useFormatDateRange = (): ((range: LocalDateRange) => string) => {
  const { t } = useTranslation("ui");
  return useCallback(
    ({ from, until }: LocalDateRange) => {
      const days = dayFormat();
      if (from && until) return days.formatRange(from, until);
      if (from) return t("dateRange.fromOnly", { date: days.format(from) });
      if (until) return t("dateRange.untilOnly", { date: days.format(until) });
      return "";
    },
    [t]
  );
};

const span = (start: Date, end: Date): LocalDateRange => ({ from: start, until: startOfDay(end) });

const QUICK_PICKS = [
  { key: "thisMonth", range: (now: Date) => span(startOfMonth(now), endOfMonth(now)) },
  {
    key: "lastMonth",
    range: (now: Date) => span(startOfMonth(subMonths(now, 1)), endOfMonth(subMonths(now, 1))),
  },
  { key: "thisQuarter", range: (now: Date) => span(startOfQuarter(now), endOfQuarter(now)) },
  { key: "thisYear", range: (now: Date) => span(startOfYear(now), endOfYear(now)) },
] as const;

/** A day clicked on the calendar: it fills whichever end is open, or starts a
 *  new range with the end left open. */
const withDay = ({ from, until }: LocalDateRange, day: Date): LocalDateRange => {
  if (from && !until) return day < from ? { from: day, until: from } : { from, until: day };
  if (!from && until) return day > until ? { from: until, until: day } : { from: day, until };
  return { from: day };
};

interface DateRangeFieldProps {
  /** Ties the trigger to a `<Label htmlFor>`. */
  id?: string;
  value: LocalDateRange;
  onChange: (next: LocalDateRange) => void;
}

/** Picks a span of days: a quick pick, or a start and an end on the calendar,
 *  where either end may be left open. */
export function DateRangeField({ id, value, onChange }: DateRangeFieldProps) {
  const { t } = useTranslation("ui");
  const field = useFieldControl({ id });
  const formatRange = useFormatDateRange();
  const [open, setOpen] = useState(false);
  const set = isDateRangeSet(value);

  return (
    <div className="flex items-center gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            {...field}
            data-empty={!set}
            className={cn(
              fieldClass,
              "min-w-0 flex-1 items-center gap-2 data-[empty=true]:text-muted-foreground"
            )}
          >
            <CalendarIcon className="h-4 w-4 shrink-0" />
            <span className="truncate">{set ? formatRange(value) : t("dateRange.any")}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <div className="flex flex-wrap gap-1 border-b p-2">
            {QUICK_PICKS.map((pick) => (
              <Button
                key={pick.key}
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  onChange(pick.range(new Date()));
                  setOpen(false);
                }}
              >
                {t(`dateRange.${pick.key}`)}
              </Button>
            ))}
          </div>
          <Calendar
            mode="range"
            selected={{ from: value.from, to: value.until }}
            onSelect={(_range, day) => onChange(withDay(value, day))}
            defaultMonth={value.from ?? value.until}
          />
          <div className="space-y-1 border-t p-2 text-sm">
            {(["from", "until"] as const).map((end) => {
              const day = value[end];
              return (
                <div key={end} className="flex h-7 items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t(`dateRange.${end}Label`)}</span>
                  <span className="flex items-center gap-1">
                    {day ? dayFormat().format(day) : t("dateRange.open")}
                    {day ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        aria-label={t(`dateRange.${end}Remove`)}
                        onClick={() => onChange({ ...value, [end]: undefined })}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    ) : null}
                  </span>
                </div>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
      {set ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("dateRange.clear")}
          onClick={() => onChange({})}
        >
          <X className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  );
}
