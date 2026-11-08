import {
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  startOfWeek,
} from "date-fns";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

import type { CalendarEntry, CalendarViewMode } from "../CalendarView";
import { buildEntriesByDate, dateKey, WEEKDAY_KEYS, type WeekStartsOn } from "./shared";

type MonthNumber = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;

export function YearView({
  entries,
  focusDate,
  weekStartsOn,
  onFocusDateChange,
  onViewModeChange,
}: {
  entries: CalendarEntry[];
  focusDate: Date;
  weekStartsOn: WeekStartsOn;
  onFocusDateChange: (date: Date) => void;
  onViewModeChange: (mode: CalendarViewMode) => void;
}) {
  const { t } = useTranslation(["dates"]);

  const year = focusDate.getFullYear();

  const entriesByDate = useMemo(
    () => buildEntriesByDate(entries, { start: new Date(year, 0, 1), end: new Date(year, 11, 31) }),
    [entries, year]
  );

  const months = useMemo(() => Array.from({ length: 12 }, (_, i) => new Date(year, i, 1)), [year]);

  const weekdayLabelsShort = useMemo(() => {
    const labels = WEEKDAY_KEYS.map((key) => ({
      key,
      label: t(`dates:weekdaysShort.${key}`).charAt(0),
    }));
    return labels.slice(weekStartsOn).concat(labels.slice(0, weekStartsOn));
  }, [weekStartsOn, t]);

  return (
    <div className="grid grid-cols-fill-56/4 gap-6">
      {months.map((monthDate) => {
        const days = eachDayOfInterval({
          start: startOfWeek(monthDate, { weekStartsOn }),
          end: endOfWeek(endOfMonth(monthDate), { weekStartsOn }),
        });
        const monthIndex = (monthDate.getMonth() + 1) as MonthNumber;

        return (
          <div key={monthIndex} className="space-y-1">
            <p className="font-semibold text-sm">{t(`dates:months.${monthIndex}`)}</p>
            {/* Mini weekday header */}
            <div className="grid grid-cols-7 text-center">
              {weekdayLabelsShort.map(({ key, label }) => (
                <div key={key} className="py-0.5 font-medium text-3xs text-muted-foreground">
                  {label}
                </div>
              ))}
            </div>
            {/* Mini day grid */}
            <div className="grid grid-cols-7 text-center">
              {days.map((day) => {
                const key = dateKey(day);
                const dayEntries = entriesByDate.get(key) ?? [];
                const inMonth = isSameMonth(day, monthDate);

                return (
                  <button
                    key={key}
                    type="button"
                    className={cn(
                      "relative flex h-8 w-full flex-col items-center justify-start gap-0 rounded pt-0.5 text-3xs transition-colors",
                      !inMonth && "text-transparent",
                      inMonth && "hover:bg-accent",
                      isToday(day) && inMonth && "bg-primary font-bold text-primary-foreground"
                    )}
                    disabled={!inMonth}
                    tabIndex={inMonth ? 0 : -1}
                    onClick={() => {
                      onFocusDateChange(day);
                      onViewModeChange("month");
                    }}
                  >
                    {format(day, "d")}
                    {inMonth && dayEntries.length > 0 && dayEntries.length <= 3 && (
                      <div className="flex gap-px">
                        {dayEntries.map((entry) => (
                          <span
                            key={entry.id}
                            className="h-1 w-1 rounded-full"
                            style={{ backgroundColor: entry.color || "var(--primary)" }}
                          />
                        ))}
                      </div>
                    )}
                    {inMonth && dayEntries.length > 3 && (
                      <span
                        className="rounded-full px-1 font-bold text-3xs text-white leading-tight"
                        style={{ backgroundColor: "var(--primary)" }}
                      >
                        {dayEntries.length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
