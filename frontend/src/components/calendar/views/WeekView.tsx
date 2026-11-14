import { addDays, eachDayOfInterval, format, isToday, startOfWeek } from "date-fns";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

import {
  type CalendarGridViewProps,
  computeSpanPlacements,
  DayColumn,
  DraggableEntryButton,
  dateKey,
  EntryType,
  HourGutter,
  kindLabelKey,
  laneSpans,
  SPAN_BAR_GAP,
  SPAN_BAR_HEIGHT,
  type SpanPlacement,
  WEEKDAY_KEYS,
  type WeekStartsOn,
} from "./shared";

export function WeekView({
  entries,
  focusDate,
  weekStartsOn,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: CalendarGridViewProps & { weekStartsOn: WeekStartsOn }) {
  const { t } = useTranslation(["common", "dates"]);

  const weekDays = useMemo(() => {
    const start = startOfWeek(focusDate, { weekStartsOn });
    return eachDayOfInterval({ start, end: addDays(start, 6) });
  }, [focusDate, weekStartsOn]);

  // The top span bar holds ONLY all-day entries. Timed entries — including
  // multi-day ones — render as clipped blocks in each day's time grid below.
  const timedEntries = useMemo(() => entries.filter((e) => !e.allDay), [entries]);

  // Multi-day all-day spans plus single-day all-day chips (one column each),
  // laned together.
  const allSpans = useMemo(() => {
    const { spans, singleDay } = computeSpanPlacements(
      weekDays,
      entries.filter((e) => e.allDay)
    );
    const merged: SpanPlacement[] = [...spans];
    for (const [key, dayEntries] of singleDay) {
      const col = weekDays.findIndex((d) => dateKey(d) === key);
      if (col === -1) continue;
      for (const entry of dayEntries) {
        merged.push({ entry, startCol: col, spanCols: 1, lane: 0, showTitle: true });
      }
    }
    return { spans: merged, maxLane: laneSpans(merged) };
  }, [weekDays, entries]);

  const spanAreaHeight = allSpans.maxLane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[700px]">
        {/* Column headers */}
        <div className="grid grid-cols-[60px_repeat(7,1fr)] border-b">
          <div /> {/* Time gutter */}
          {weekDays.map((day) => (
            <div
              key={dateKey(day)}
              className={cn(
                "flex flex-col items-center py-2 font-medium text-xs",
                isToday(day) && "text-primary"
              )}
            >
              <span className="text-muted-foreground uppercase">
                {t(`dates:weekdaysShort.${WEEKDAY_KEYS[day.getDay()]}`)}
              </span>
              <span
                className={cn(
                  "mt-0.5 flex h-7 w-7 items-center justify-center rounded-full font-semibold text-sm",
                  isToday(day) && "bg-primary text-primary-foreground"
                )}
              >
                {format(day, "d")}
              </span>
            </div>
          ))}
        </div>

        {/* All-day / multi-day spanning bar area */}
        {allSpans.spans.length > 0 && (
          <div className="grid grid-cols-[60px_repeat(7,1fr)] border-b">
            <div className="flex items-start justify-end pt-1 pr-2 text-3xs text-muted-foreground">
              {t("common:calendar.allDay")}
            </div>
            <div className="relative col-span-7" style={{ height: spanAreaHeight + 4 }}>
              {allSpans.spans.map((span) => (
                <DraggableEntryButton
                  key={`${span.entry.id}-${span.startCol}`}
                  dragId={`${span.entry.id}-${span.startCol}`}
                  entry={span.entry}
                  enabled={dndEnabled}
                  onSelect={onEntryClick}
                  className={cn(
                    "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 font-medium text-2xs text-white",
                    onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                  )}
                  style={{
                    left: `calc(${(span.startCol / 7) * 100}% + 2px)`,
                    width: `calc(${(span.spanCols / 7) * 100}% - 4px)`,
                    top: span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP) + 2,
                    height: SPAN_BAR_HEIGHT,
                    backgroundColor: span.entry.color || "var(--primary)",
                  }}
                >
                  {span.entry.kind && (
                    <span className="shrink-0 rounded-sm bg-white/25 px-1 font-semibold text-3xs uppercase">
                      {t(`common:${kindLabelKey(span.entry.kind)}`)}
                    </span>
                  )}
                  <EntryType entry={span.entry} onColor />
                  <span className="truncate">{span.entry.title}</span>
                </DraggableEntryButton>
              ))}
            </div>
          </div>
        )}

        {/* Time grid with positioned blocks */}
        <div className="grid max-h-[600px] grid-cols-[60px_repeat(7,1fr)] overflow-y-auto">
          <HourGutter className="pr-2" />
          {weekDays.map((day) => (
            <DayColumn
              key={dateKey(day)}
              day={day}
              entries={timedEntries}
              onEntryClick={onEntryClick}
              onSlotClick={onSlotClick}
              dndEnabled={dndEnabled}
              compact
            />
          ))}
        </div>
      </div>
    </div>
  );
}
