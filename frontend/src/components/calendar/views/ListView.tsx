import { addDays, endOfMonth, format, isToday, startOfDay, startOfMonth } from "date-fns";
import { Clock } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { UnreadDot } from "@/components/notifications/UnreadDot";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { Checkbox } from "@/ui/checkbox";
import { dateTimeFormat } from "@/ui/lib/intl";
import { formatCompactTime as formatTime } from "@/ui/lib/timeFormat";
import { cn } from "@/ui/lib/utils";
import { PropertyValueCell } from "@/ui/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/ui/properties/propertyHelpers";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

import type { CalendarEntry } from "../CalendarView";
import { type CalendarViewBaseProps, dateKey, EntryType, kindLabelKey, parseEntry } from "./shared";

// Multi-day entries expand so each spanned day gets its own row.
type ListRow = { entry: CalendarEntry; displayDate: Date; isSpanDay: boolean };

export function ListView({
  entries,
  focusDate,
  onEntryClick,
  selectionActive = false,
  selectedEntryIds,
  isEntrySelectable,
  onToggleEntrySelection,
}: CalendarViewBaseProps & {
  selectionActive?: boolean;
  selectedEntryIds?: Set<CalendarEntry["id"]>;
  isEntrySelectable?: (entry: CalendarEntry) => boolean;
  onToggleEntrySelection?: (entry: CalendarEntry) => void;
}) {
  const { t, i18n } = useTranslation(["common"]);
  const monthName = dateTimeFormat(i18n.language, { month: "short" });
  const weekdayName = dateTimeFormat(i18n.language, { weekday: "long" });

  const rows = useMemo<ListRow[]>(() => {
    const monthStart = startOfMonth(focusDate);
    const monthEnd = endOfMonth(focusDate);
    const result: ListRow[] = [];

    for (const entry of entries) {
      // In selection mode the list is a picker for shareable entries only — hide
      // everything that can't be selected (e.g. tasks) so it can't be confused
      // for something you can bulk-edit.
      if (selectionActive && !(isEntrySelectable?.(entry) ?? false)) continue;

      const { start, end } = parseEntry(entry);
      if (Number.isNaN(start.getTime())) continue;

      const endDay = Number.isNaN(end.getTime()) ? start : end;
      const cursor = new Date(Math.max(startOfDay(start).getTime(), monthStart.getTime()));
      const last = new Date(Math.min(startOfDay(endDay).getTime(), monthEnd.getTime()));

      while (cursor <= last) {
        if (cursor >= monthStart && cursor <= monthEnd) {
          result.push({
            entry,
            displayDate: new Date(cursor),
            isSpanDay: cursor > startOfDay(start),
          });
        }
        cursor.setTime(startOfDay(addDays(cursor, 1)).getTime());
      }
    }

    result.sort((a, b) => a.displayDate.getTime() - b.displayDate.getTime());
    return result;
  }, [entries, focusDate, selectionActive, isEntrySelectable]);

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm">
        <Clock className="mb-2 h-8 w-8 opacity-50" />
        <p>{t("common:calendar.noEntries")}</p>
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-1">
        {rows.map(({ entry, displayDate, isSpanDay }) => {
          const { start, end } = parseEntry(entry);
          const chips = nonEmptyPropertySummaries(entry.properties);

          // In selection mode, only selectable entries (events) can be picked;
          // other rows (tasks) are shown dimmed and inert so they stay for
          // context without navigating away or being selectable.
          const selectable = selectionActive && (isEntrySelectable?.(entry) ?? false);
          const selected = selectable && (selectedEntryIds?.has(entry.id) ?? false);
          const interactive = selectionActive ? selectable : !!onEntryClick;

          return (
            <button
              key={`${entry.id}-${dateKey(displayDate)}`}
              type="button"
              disabled={selectionActive && !selectable}
              aria-pressed={selectable ? selected : undefined}
              className={cn(
                "flex w-full items-start gap-4 rounded-md border px-3 py-2.5 text-left text-sm transition-colors",
                isToday(displayDate) && "ring-1 ring-primary/60",
                interactive ? "cursor-pointer hover:bg-accent" : "cursor-default",
                selected && "bg-primary/5 ring-2 ring-primary",
                selectionActive && !selectable && "opacity-50"
              )}
              onClick={() =>
                selectionActive
                  ? selectable && onToggleEntrySelection?.(entry)
                  : onEntryClick?.(entry)
              }
            >
              {selectable && (
                <Checkbox
                  checked={selected}
                  className="pointer-events-none mt-0.5 shrink-0 border-2"
                  aria-hidden="true"
                />
              )}
              {/* Date column: day + month */}
              <div className="flex w-14 shrink-0 flex-col items-center pt-0.5 leading-tight">
                <span className="font-bold text-lg">{format(displayDate, "d")}</span>
                <span className="text-2xs text-muted-foreground uppercase">
                  {monthName.format(displayDate)}
                </span>
              </div>

              {/* Weekday name */}
              <span className="w-24 shrink-0 pt-1 text-muted-foreground text-xs">
                {weekdayName.format(displayDate)}
              </span>

              {/* Color dot */}
              <span
                className="mt-1.5 h-3 w-3 shrink-0 rounded-full bg-muted-foreground"
                style={{ backgroundColor: entry.color || undefined }}
                aria-hidden="true"
              />

              {/* Title + description + property chips */}
              <div className="min-w-0 flex-1">
                {entry.kind && (
                  <span className="mr-1.5 rounded-sm bg-muted px-1 font-semibold text-3xs text-muted-foreground uppercase">
                    {t(`common:${kindLabelKey(entry.kind)}`)}
                  </span>
                )}
                <EntryType entry={entry} className="mr-1.5 align-middle" />
                <span className="font-medium">{entry.title}</span>
                {entry.unread ? <UnreadDot className="ml-2 inline-block align-middle" /> : null}
                {entry.description && (
                  <p className="mt-0.5 line-clamp-2 text-muted-foreground text-xs">
                    {entry.description}
                  </p>
                )}
                {chips.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {chips.map((summary) => (
                      <PropertyValueCell
                        key={summary.property_id}
                        summary={summary}
                        variant="chip"
                      />
                    ))}
                  </div>
                )}
                <TagBadgeList tags={entry.tags ?? []} className="mt-1" />
              </div>

              {/* Attendee avatars */}
              {entry.attendees && entry.attendees.length > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex shrink-0 -space-x-1.5 pt-0.5">
                      {entry.attendees.slice(0, 4).map((att) => {
                        const src = resolveUploadUrl(att.avatarUrl) || undefined;
                        return (
                          <Avatar
                            key={att.userId}
                            className="h-6 w-6 border-2 border-card font-semibold text-3xs uppercase"
                          >
                            {src ? <AvatarImage src={src} alt={att.name} /> : null}
                            <AvatarFallback userId={att.userId}>
                              {getInitials(att.name)}
                            </AvatarFallback>
                          </Avatar>
                        );
                      })}
                      {entry.attendees.length > 4 && (
                        <Avatar className="h-6 w-6 border-2 border-card font-semibold text-3xs">
                          <AvatarFallback>+{entry.attendees.length - 4}</AvatarFallback>
                        </Avatar>
                      )}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <div className="space-y-0.5 text-xs">
                      {entry.attendees.map((att) => (
                        <div key={att.userId}>{att.name}</div>
                      ))}
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Time */}
              <span className="shrink-0 pt-1 text-muted-foreground text-xs">
                {entry.allDay || isSpanDay
                  ? t("common:calendar.allDay")
                  : `${formatTime(start)} – ${formatTime(end)}`}
              </span>
            </button>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
