/**
 * The community home's look ahead: everything in the community with a date in
 * the next seven days — events, open tasks starting or due, projects starting
 * or ending, and polls closing.
 *
 * One request, the calendar's own aggregate, so each kind is read under the
 * gates its own list uses. Drawn as the front page's example cards are: the
 * tool's tile, what it is, and a strip saying when, lit for today.
 */

import { Link } from "@tanstack/react-router";
import { addDays, differenceInCalendarDays, endOfDay, startOfDay } from "date-fns";
import { CalendarClock } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { type ListCalendarEntriesParams, Tool } from "@/api/generated/initiativeAPI.schemas";
import { utcDateKey } from "@/components/calendar/eventCalendarEntry";
import { ToolIconTile } from "@/components/initiatives/ToolSkeletons";
import { useCalendarEntries } from "@/hooks/useCalendarEntries";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { browserTimezone } from "@/lib/timezones";
import { entityRefRoute, taskRoute, toolDetailRoute } from "@/lib/tools";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { dateTimeFormat } from "@/ui/lib/intl";
import { formatCompactTime } from "@/ui/lib/timeFormat";
import { cn } from "@/ui/lib/utils";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

const DAYS_AHEAD = 7;

type Kind = "event" | "taskStart" | "taskDue" | "projectStart" | "projectEnd" | "pollCloses";

type Upcoming = {
  key: string;
  tool: Tool;
  kind: Kind;
  title: string;
  at: Date;
  /** A whole day rather than a moment in it. */
  allDay: boolean;
  initiativeId: number | null;
  /** The project a task is in. */
  projectName?: string | null;
  to: string;
  search?: Record<string, string>;
};

/** A date the server keeps as a whole day, `YYYY-MM-DD…`, as that day here. */
const localDay = (value: string) => new Date(`${value.slice(0, 10)}T00:00:00`);

export const CommunityComingUp = () => {
  const { t, i18n } = useTranslation("communityHome");
  const gp = useCommunityPath();
  const initiativesQuery = useInitiatives();

  // Today and the six days after it, read once: the page is a glance.
  const range = useMemo(() => {
    const start = startOfDay(new Date());
    return { start, end: endOfDay(addDays(start, DAYS_AHEAD - 1)) };
  }, []);

  const params = useMemo(
    (): ListCalendarEntriesParams => ({
      start_after: range.start.toISOString(),
      start_before: range.end.toISOString(),
      tz: browserTimezone(),
      include_projects: true,
      include_polls: true,
      // A finished task has nothing coming up.
      conditions: [
        { field: "status_category", op: "in_", value: ["backlog", "todo", "in_progress"] },
      ],
    }),
    [range]
  );
  const entriesQuery = useCalendarEntries(params);

  const items = useMemo<Upcoming[]>(() => {
    const data = entriesQuery.data;
    if (!data) return [];
    const result: Upcoming[] = [];

    for (const event of data.events) {
      result.push({
        key: `event-${event.id}-${event.start_at}`,
        tool: Tool.calendar,
        kind: "event",
        title: event.title,
        // An all-day event's date is a UTC date, the same one for everybody.
        at: event.all_day ? localDay(utcDateKey(event.start_at)) : new Date(event.start_at),
        allDay: event.all_day,
        initiativeId: event.initiative_id,
        to: gp(entityRefRoute("calendar-event", event.id)),
        search: event.original_start ? { occurrence: event.original_start } : undefined,
      });
    }

    // A repeating task's next date is the current task's, moved there.
    for (const task of [...data.tasks, ...data.task_occurrences]) {
      const marks: [Kind, string | null | undefined][] = [
        ["taskStart", task.start_date],
        ["taskDue", task.due_date],
      ];
      for (const [kind, date] of marks) {
        if (!date) continue;
        // Read in the reader's own day, as the calendar draws it.
        const at = new Date(date);
        if (at < range.start || at > range.end) continue;
        result.push({
          key: `${kind}-${task.id}-${date}`,
          tool: Tool.project,
          kind,
          title: task.title,
          at,
          allDay: true,
          initiativeId: task.initiative_id,
          projectName: task.project_name,
          to: gp(taskRoute(task.initiative_id, task.project_id, task.id)),
        });
      }
    }

    for (const project of data.projects) {
      const marks: [Kind, string | null | undefined][] = [
        ["projectStart", project.start_date],
        ["projectEnd", project.end_date],
      ];
      for (const [kind, date] of marks) {
        if (!date) continue;
        const at = localDay(date);
        if (at < range.start || at > range.end) continue;
        result.push({
          key: `${kind}-${project.id}`,
          tool: Tool.project,
          kind,
          title: project.name,
          at,
          allDay: true,
          initiativeId: project.initiative_id ?? null,
          to: gp(toolDetailRoute(Tool.project, project.initiative_id ?? null, project.id)),
        });
      }
    }

    for (const post of data.polls) {
      if (!post.poll?.closes_at) continue;
      result.push({
        key: `poll-${post.id}`,
        tool: Tool.post,
        kind: "pollCloses",
        title: post.poll.question || post.name,
        at: new Date(post.poll.closes_at),
        allDay: false,
        initiativeId: post.initiative_id,
        to: gp(toolDetailRoute(Tool.post, post.initiative_id, post.id)),
      });
    }

    return result.sort((a, b) => a.at.getTime() - b.at.getTime());
  }, [entriesQuery.data, gp, range]);

  const initiativeNames = useMemo(
    () =>
      new Map((initiativesQuery.data ?? []).map((initiative) => [initiative.id, initiative.name])),
    [initiativesQuery.data]
  );

  const dayLabel = (at: Date) => {
    const days = differenceInCalendarDays(at, range.start);
    if (days <= 0) return t("comingUp.today");
    if (days === 1) return t("comingUp.tomorrow");
    return dateTimeFormat(i18n.language, { weekday: "short", day: "numeric" }).format(at);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("comingUp.title")}</CardTitle>
        <CardDescription>{t("comingUp.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {entriesQuery.isLoading ? (
          <div className="grid grid-cols-fill-60/3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
              <Skeleton key={i} className="h-28 rounded-2xl" />
            ))}
          </div>
        ) : entriesQuery.isError ? (
          <StatusMessage onRetry={entriesQuery.refetch} />
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground text-sm">
            <CalendarClock className="h-8 w-8 opacity-50" />
            <span>{t("comingUp.empty")}</span>
          </div>
        ) : (
          <ul className="grid grid-cols-fill-60/3 gap-3">
            {items.map((item) => {
              const today = differenceInCalendarDays(item.at, range.start) <= 0;
              const where = [
                item.projectName,
                item.initiativeId != null ? initiativeNames.get(item.initiativeId) : null,
              ].filter(Boolean);
              return (
                <li key={item.key}>
                  <Link
                    to={item.to}
                    search={item.search}
                    className="flex h-full flex-col gap-3 rounded-2xl border bg-card p-3 transition-colors hover:bg-accent"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <ToolIconTile tool={item.tool} active={today} />
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-sm">{item.title}</p>
                        {where.length > 0 ? (
                          <p className="truncate text-muted-foreground text-xs">
                            {where.join(" · ")}
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <p
                      className={cn(
                        "mt-auto flex items-center gap-2 rounded-xl px-3 py-2 font-medium text-xs",
                        today ? "bg-primary/10" : "bg-muted"
                      )}
                    >
                      <span className="truncate">
                        {t(`comingUp.kind.${item.kind}`)}
                        {item.allDay ? null : ` · ${formatCompactTime(item.at)}`}
                      </span>
                      <span
                        className={cn(
                          "ml-auto whitespace-nowrap rounded-full px-2 py-0.5 font-bold text-2xs",
                          today
                            ? "bg-primary text-primary-foreground"
                            : "bg-background text-muted-foreground"
                        )}
                      >
                        {dayLabel(item.at)}
                      </span>
                    </p>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
};
