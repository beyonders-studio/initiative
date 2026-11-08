import {
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  startOfDay,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { formatCompactTime as formatTime } from "@/ui/lib/timeFormat";
import { cn } from "@/ui/lib/utils";

import {
  type CalendarGridViewProps,
  computeSpanPlacements,
  DraggableEntryButton,
  DroppableDiv,
  dateKey,
  EntryType,
  kindLabelKey,
  parseEntry,
  SPAN_BAR_GAP,
  SPAN_BAR_HEIGHT,
  WEEKDAY_KEYS,
  type WeekStartsOn,
} from "./shared";

const MAX_VISIBLE_ENTRIES = 3;

export function MonthView({
  entries,
  focusDate,
  weekStartsOn,
  onEntryClick,
  onSlotClick,
  dndEnabled = false,
}: CalendarGridViewProps & { weekStartsOn: WeekStartsOn }) {
  const { t } = useTranslation(["common", "dates"]);

  const weekdayLabels = useMemo(() => {
    const labels = WEEKDAY_KEYS.map((key) => t(`dates:weekdaysShort.${key}`));
    return labels.slice(weekStartsOn).concat(labels.slice(0, weekStartsOn));
  }, [weekStartsOn, t]);

  // The month's days split into week rows, each with its span placements.
  const weekRows = useMemo(() => {
    const days = eachDayOfInterval({
      start: startOfWeek(startOfMonth(focusDate), { weekStartsOn }),
      end: endOfWeek(endOfMonth(focusDate), { weekStartsOn }),
    });
    const rows: Date[][] = [];
    for (let i = 0; i < days.length; i += 7) {
      rows.push(days.slice(i, i + 7));
    }
    return rows.map((week) => ({ week, ...computeSpanPlacements(week, entries) }));
  }, [focusDate, weekStartsOn, entries]);

  return (
    <div className="space-y-2 overflow-x-auto sm:overflow-visible">
      <div className="min-w-[700px] sm:min-w-0">
        {/* Weekday headers */}
        <div className="grid grid-cols-7 text-center font-semibold text-2xs text-muted-foreground uppercase sm:text-xs">
          {weekdayLabels.map((day) => (
            <div key={day} className="py-2">
              {day}
            </div>
          ))}
        </div>

        {/* Week rows */}
        <div className="space-y-px rounded-lg border bg-border">
          {weekRows.map(({ week, spans, singleDay, maxLane }) => {
            const spanAreaHeight = maxLane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP);

            return (
              <div key={dateKey(week[0])} className="relative">
                {/* Day cells */}
                <div className="grid grid-cols-7 gap-px">
                  {week.map((day) => {
                    const key = dateKey(day);
                    const daySingles = singleDay.get(key) ?? [];
                    const overflow = daySingles.length - MAX_VISIBLE_ENTRIES;

                    return (
                      <DroppableDiv
                        key={key}
                        dropId={`day:${key}`}
                        data={{ type: "day", dateKey: key }}
                        disabled={!dndEnabled}
                        overClassName="ring-2 ring-primary/60 ring-inset"
                        role={onSlotClick ? "button" : undefined}
                        tabIndex={onSlotClick ? 0 : undefined}
                        className={cn(
                          "flex flex-col gap-0.5 bg-card p-1.5 text-left text-xs",
                          !isSameMonth(day, focusDate) && "bg-muted/40 text-muted-foreground",
                          isToday(day) && "ring-2 ring-primary/80",
                          onSlotClick && "cursor-pointer"
                        )}
                        style={{ minHeight: 80 + spanAreaHeight }}
                        onClick={(e) => {
                          if (
                            e.target === e.currentTarget ||
                            (e.target as HTMLElement).closest("[data-slot='day-number']")
                          ) {
                            onSlotClick?.(startOfDay(day));
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onSlotClick?.(startOfDay(day));
                          }
                        }}
                      >
                        <div className="flex items-center justify-between" data-slot="day-number">
                          <span className="font-medium text-sm">{format(day, "d")}</span>
                          {isToday(day) && (
                            <span className="font-semibold text-3xs text-primary uppercase">
                              {t("common:calendar.today")}
                            </span>
                          )}
                        </div>
                        {/* Spacer for span bars */}
                        {spanAreaHeight > 0 && <div style={{ height: spanAreaHeight }} />}
                        {/* Single-day timed entries: dot + time + title */}
                        {daySingles.slice(0, MAX_VISIBLE_ENTRIES).map((entry) => (
                          <DraggableEntryButton
                            key={entry.id}
                            entry={entry}
                            enabled={dndEnabled}
                            onSelect={onEntryClick}
                            className={cn(
                              "flex w-full items-center gap-1 text-left text-2xs leading-tight",
                              onEntryClick
                                ? "cursor-pointer rounded px-0.5 hover:bg-accent"
                                : "cursor-default"
                            )}
                          >
                            <span
                              className={cn(
                                "h-2 w-2 shrink-0 rounded-full",
                                entry.kind === "start" && "border-2 bg-transparent"
                              )}
                              style={
                                entry.kind === "start"
                                  ? { borderColor: entry.color || "var(--primary)" }
                                  : { backgroundColor: entry.color || "var(--primary)" }
                              }
                            />
                            {entry.kind ? (
                              <span className="shrink-0 font-semibold text-3xs text-muted-foreground uppercase">
                                {t(`common:${kindLabelKey(entry.kind)}`)}
                              </span>
                            ) : (
                              <span className="shrink-0 text-3xs text-muted-foreground">
                                {entry.allDay ? "" : formatTime(parseEntry(entry).start)}
                              </span>
                            )}
                            <EntryType entry={entry} />
                            <span className="truncate">{entry.title}</span>
                          </DraggableEntryButton>
                        ))}
                        {overflow > 0 && (
                          <p className="text-3xs text-muted-foreground">
                            {t("common:calendar.more", { count: overflow })}
                          </p>
                        )}
                      </DroppableDiv>
                    );
                  })}
                </div>

                {/* Spanning bars — absolutely positioned over the grid */}
                {spans.map((span) => {
                  // A span crossing multiple week rows renders one strip per
                  // row; disambiguate the dnd-kit id by week so registrations
                  // don't collide.
                  const weekDragKey = `${span.entry.id}-${dateKey(week[span.startCol])}`;

                  return (
                    <DraggableEntryButton
                      key={weekDragKey}
                      dragId={weekDragKey}
                      entry={span.entry}
                      enabled={dndEnabled}
                      onSelect={onEntryClick}
                      className={cn(
                        "absolute z-10 flex items-center gap-1 overflow-hidden rounded px-2 font-medium text-2xs text-white",
                        onEntryClick ? "cursor-pointer hover:brightness-90" : "cursor-default"
                      )}
                      style={{
                        left: `calc(${(span.startCol / 7) * 100}% + 4px)`,
                        width: `calc(${(span.spanCols / 7) * 100}% - 8px)`,
                        // Offset below the day number line (~24px)
                        top: 24 + span.lane * (SPAN_BAR_HEIGHT + SPAN_BAR_GAP),
                        height: SPAN_BAR_HEIGHT,
                        backgroundColor: span.entry.color || "var(--primary)",
                      }}
                    >
                      <EntryType
                        entry={span.entry}
                        onColor
                        className={cn(!span.showTitle && "opacity-70")}
                      />
                      <span className={cn("truncate", !span.showTitle && "opacity-70")}>
                        {span.entry.title}
                      </span>
                    </DraggableEntryButton>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
