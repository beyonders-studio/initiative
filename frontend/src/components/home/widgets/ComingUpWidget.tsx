/**
 * The days ahead, from every community: events on the reader's calendars and
 * their open tasks starting or falling due, as an agenda grouped by day.
 *
 * One request, My Calendar's own (`/me/calendar-entries`), over today and the
 * days the reader chose.
 */

import { Link } from "@tanstack/react-router";
import { addDays, differenceInCalendarDays, endOfDay, startOfDay } from "date-fns";
import { CalendarClock } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { type ListMyCalendarEntriesParams, Tool } from "@/api/generated/initiativeAPI.schemas";
import { utcDateKey } from "@/components/calendar/eventCalendarEntry";
import { HomeWidgetCard, HomeWidgetNotice } from "@/components/home/HomeWidgetCard";
import { ToolIconTile } from "@/components/initiatives/ToolSkeletons";
import { useMyCalendarEntries } from "@/hooks/useCalendarEntries";
import { useCommunities } from "@/hooks/useCommunities";
import { communityPath } from "@/lib/communityUrl";
import { browserTimezone } from "@/lib/timezones";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { dateTimeFormat } from "@/ui/lib/intl";
import { formatCompactTime } from "@/ui/lib/timeFormat";
import { useLiveClockValue } from "@/ui/lib/useRelativeTime";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

import type { HomeWidgetProps, HomeWidgetSettingsProps } from "./types";

const DAY_CHOICES = [3, 7, 14, 30] as const;
const DEFAULT_DAYS = 7;

const daysOf = (options: Record<string, unknown>) =>
  DAY_CHOICES.includes(options.days as (typeof DAY_CHOICES)[number])
    ? (options.days as number)
    : DEFAULT_DAYS;

type Kind = "event" | "taskStart" | "taskDue";

type Upcoming = {
  key: string;
  tool: Tool;
  kind: Kind;
  title: string;
  at: Date;
  allDay: boolean;
  where: string;
  to: string;
  search?: Record<string, string>;
};

/** A date the server keeps as a whole day, `YYYY-MM-DD…`, as that day here. */
const localDay = (value: string) => new Date(`${value.slice(0, 10)}T00:00:00`);

export const ComingUpWidget = ({ options }: HomeWidgetProps) => {
  const { t, i18n } = useTranslation(["home", "communityHome"]);
  const { communities } = useCommunities();
  const days = daysOf(options);

  // Today and the days after it; rolls over at midnight on its own.
  const today = useLiveClockValue((now) => startOfDay(now).getTime());
  const range = useMemo(() => {
    const start = new Date(today);
    return { start, end: endOfDay(addDays(start, days - 1)) };
  }, [today, days]);

  const params = useMemo(
    (): ListMyCalendarEntriesParams => ({
      start_after: range.start.toISOString(),
      start_before: range.end.toISOString(),
      tz: browserTimezone(),
      include_events: true,
      include_tasks: true,
      // A finished task has nothing coming up.
      conditions: [
        { field: "status_category", op: "in_", value: ["backlog", "todo", "in_progress"] },
      ],
    }),
    [range]
  );
  const entriesQuery = useMyCalendarEntries(params);

  const communityNames = useMemo(
    () => new Map(communities.map((community) => [community.id, community.name])),
    [communities]
  );
  const multiCommunity = communities.length > 1;

  const items = useMemo<Upcoming[]>(() => {
    const data = entriesQuery.data;
    if (!data) return [];
    const result: Upcoming[] = [];
    const placeOf = (communityId: number | null | undefined, ...parts: (string | null)[]) =>
      [...parts, multiCommunity && communityId != null ? communityNames.get(communityId) : null]
        .filter(Boolean)
        .join(" · ");

    for (const event of data.events) {
      result.push({
        key: `event-${event.community_id}-${event.id}-${event.start_at}`,
        tool: Tool.calendar,
        kind: "event",
        title: event.title,
        // An all-day event's date is a UTC date, the same one for everybody.
        at: event.all_day ? localDay(utcDateKey(event.start_at)) : new Date(event.start_at),
        allDay: event.all_day,
        where: placeOf(event.community_id, event.location),
        to: communityPath(event.community_id, entityRefRoute("calendar-event", event.id)),
        search: event.original_start ? { occurrence: event.original_start } : undefined,
      });
    }

    // A repeating task's next date is the current task's, moved there.
    for (const task of [...data.tasks, ...data.task_occurrences]) {
      if (task.community_id == null) continue;
      const marks: [Kind, string | null | undefined][] = [
        ["taskStart", task.start_date],
        ["taskDue", task.due_date],
      ];
      for (const [kind, date] of marks) {
        if (!date) continue;
        const at = new Date(date);
        if (at < range.start || at > range.end) continue;
        const path =
          task.initiative_id != null
            ? taskRoute(task.initiative_id, task.project_id, task.id)
            : entityRefRoute("task", task.id);
        result.push({
          key: `${kind}-${task.community_id}-${task.id}-${date}`,
          tool: Tool.project,
          kind,
          title: task.title,
          at,
          allDay: true,
          where: placeOf(task.community_id, task.project_name ?? null),
          to: communityPath(task.community_id, path),
        });
      }
    }

    return result.sort((a, b) => a.at.getTime() - b.at.getTime());
  }, [entriesQuery.data, range, communityNames, multiCommunity]);

  const groups = useMemo(() => {
    const byDay = new Map<number, Upcoming[]>();
    for (const item of items) {
      const offset = Math.max(differenceInCalendarDays(item.at, range.start), 0);
      byDay.set(offset, [...(byDay.get(offset) ?? []), item]);
    }
    return [...byDay];
  }, [items, range]);

  const dayLabel = (offset: number) => {
    if (offset === 0) return t("communityHome:comingUp.today");
    if (offset === 1) return t("communityHome:comingUp.tomorrow");
    return dateTimeFormat(i18n.language, {
      weekday: "long",
      month: "short",
      day: "numeric",
    }).format(addDays(range.start, offset));
  };

  return (
    <HomeWidgetCard icon={CalendarClock} title={t("widgets.comingUp.title")} to="/my-calendar">
      {entriesQuery.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : entriesQuery.isError ? (
        <StatusMessage onRetry={entriesQuery.refetch} />
      ) : groups.length === 0 ? (
        <HomeWidgetNotice
          icon={CalendarClock}
          action={
            <Button asChild size="sm" variant="outline">
              <Link to="/my-calendar">{t("widgets.comingUp.openCalendar")}</Link>
            </Button>
          }
        >
          {t("widgets.comingUp.empty", { count: days })}
        </HomeWidgetNotice>
      ) : (
        <div className="space-y-4">
          {groups.map(([offset, dayItems]) => (
            <section key={offset} className="space-y-1.5">
              <h3
                className={cn(
                  "font-semibold text-xs uppercase tracking-wide",
                  offset === 0 ? "text-primary" : "text-muted-foreground"
                )}
              >
                {dayLabel(offset)}
              </h3>
              <ul className="space-y-1">
                {dayItems.map((item) => (
                  <li key={item.key}>
                    <Link
                      to={item.to}
                      search={item.search}
                      className="flex items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-accent"
                    >
                      <ToolIconTile tool={item.tool} active={offset === 0} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-sm">{item.title}</p>
                        <p className="truncate text-muted-foreground text-xs">
                          {t(`communityHome:comingUp.kind.${item.kind}`)}
                          {item.allDay ? null : ` · ${formatCompactTime(item.at)}`}
                          {item.where ? ` · ${item.where}` : null}
                        </p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </HomeWidgetCard>
  );
};

export const ComingUpSettings = ({ options, onChange }: HomeWidgetSettingsProps) => {
  const { t } = useTranslation("home");
  return (
    <Field label={t("widgets.comingUp.days")}>
      <Select
        value={String(daysOf(options))}
        onValueChange={(value) => onChange({ ...options, days: Number(value) })}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {DAY_CHOICES.map((count) => (
            <SelectItem key={count} value={String(count)}>
              {t("widgets.comingUp.daysOption", { count })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Field>
  );
};
