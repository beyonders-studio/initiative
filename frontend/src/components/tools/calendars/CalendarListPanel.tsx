import { Link } from "@tanstack/react-router";
import { CalendarDays, ChevronDown, Plus, Settings2 } from "lucide-react";
import { type ComponentProps, type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";

import { type CalendarSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** A derived, read-only "calendar" for one project's tasks — rendered from the
 * calendar-entries tasks payload, never stored server-side. */
export interface ProjectTaskCalendar {
  projectId: number;
  communityId: number;
  name: string;
  color: string;
}

interface CalendarListPanelProps {
  calendars: CalendarSummary[];
  projectCalendars: ProjectTaskCalendar[];
  /** Callback predicates instead of id sets: callers own the keying (the My
   * Calendar page is cross-community, where per-community ids collide). Visibility
   * defaults ON so new calendars appear checked. */
  isCalendarHidden: (calendar: CalendarSummary) => boolean;
  isProjectHidden: (project: ProjectTaskCalendar) => boolean;
  onToggleCalendar: (calendar: CalendarSummary) => void;
  onToggleProject: (project: ProjectTaskCalendar) => void;
  /** Optional display label override (e.g. community-suffixed cross-community names). */
  calendarLabel?: (calendar: CalendarSummary) => string;
  /** Settings link target for a manageable calendar; null hides the link. */
  settingsPathFor?: (calendar: CalendarSummary) => string | null;
}

interface CalendarPickerProps {
  calendars: CalendarSummary[];
  isCalendarHidden: (calendar: CalendarSummary) => boolean;
  onToggleCalendar: (calendar: CalendarSummary) => void;
  /** Turns every calendar back on, loaded here or not. */
  onShowAll: () => void;
  /** Settings link target for a manageable calendar; null hides the link. */
  settingsPathFor?: (calendar: CalendarSummary) => string | null;
  canCreate: boolean;
  onCreate: () => void;
}

interface ToggleRowProps {
  color: string;
  label: string;
  shown: boolean;
  onToggle: () => void;
  className?: string;
  /** Marks after the label. */
  children?: ReactNode;
}

/** A checkbox, a color dot and a name: one calendar or project to show or hide. */
const ToggleRow = ({ color, label, shown, onToggle, className, children }: ToggleRowProps) => {
  const id = useId();
  return (
    <li className={cn("group flex items-center gap-2 rounded", className)}>
      <Checkbox id={id} checked={shown} onCheckedChange={onToggle} />
      <span
        aria-hidden
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ backgroundColor: color }}
      />
      <Label htmlFor={id} className="min-w-0 flex-1 cursor-pointer truncate font-normal text-sm">
        {label}
      </Label>
      {children}
    </li>
  );
};

interface CalendarRowProps {
  calendar: CalendarSummary;
  label?: string;
  shown: boolean;
  unread: boolean;
  onToggle: () => void;
  settingsPathFor?: (calendar: CalendarSummary) => string | null;
  className: string;
}

const CalendarRow = ({
  calendar,
  label,
  shown,
  unread,
  onToggle,
  settingsPathFor,
  className,
}: CalendarRowProps) => {
  const { t } = useTranslation("calendars");
  const settingsPath = calendar.can.edit ? (settingsPathFor?.(calendar) ?? null) : null;
  return (
    <ToggleRow
      color={calendar.color}
      label={label ?? calendar.name}
      shown={shown}
      onToggle={onToggle}
      className={className}
    >
      {unread ? <UnreadDot /> : null}
      {settingsPath ? (
        <Link
          to={settingsPath}
          // Shown on hover, and whenever it has the keyboard's focus.
          className="rounded text-muted-foreground opacity-0 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100"
          aria-label={t("panel.calendarSettings", { name: calendar.name })}
        >
          <Settings2 className="h-4 w-4" />
        </Link>
      ) : null}
    </ToggleRow>
  );
};

interface ProjectTaskTogglesProps {
  projects: ProjectTaskCalendar[];
  isProjectHidden: (project: ProjectTaskCalendar) => boolean;
  onToggleProject: (project: ProjectTaskCalendar) => void;
  className?: string;
}

/** One checkbox per project with tasks in view, to show or hide its tasks. */
export const ProjectTaskToggles = ({
  projects,
  isProjectHidden,
  onToggleProject,
  className,
}: ProjectTaskTogglesProps) => (
  <ul className={className}>
    {projects.map((project) => (
      <ToggleRow
        key={`${project.communityId}-${project.projectId}`}
        color={project.color}
        label={project.name}
        shown={!isProjectHidden(project)}
        onToggle={() => onToggleProject(project)}
        className="px-1 py-0.5"
      />
    ))}
  </ul>
);

/** Which calendars the page overlays, as the page's title: the trigger names
 *  what is showing, and opens a checklist of every calendar with "All
 *  calendars" at its head. */
export const CalendarPicker = ({
  calendars,
  isCalendarHidden,
  onToggleCalendar,
  onShowAll,
  settingsPathFor,
  canCreate,
  onCreate,
}: CalendarPickerProps) => {
  const { t } = useTranslation("calendars");
  const unread = useUnreadTree();
  const allId = useId();
  const shown = calendars.filter((calendar) => !isCalendarHidden(calendar));
  const allShown = shown.length === calendars.length;
  // What is showing, read as the page's title.
  const label =
    calendars.length === 0
      ? t("panel.calendars")
      : allShown
        ? t("picker.all")
        : shown.length === 1
          ? shown[0].name
          : shown.length === 0
            ? t("picker.none")
            : t("picker.some", { count: shown.length });

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          // Takes its type from the title it stands in.
          className="inline-flex min-w-0 max-w-full items-center gap-2 rounded-md text-left hover:bg-foreground/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="min-w-0 truncate">{label}</span>
          <ChevronDown className="h-[0.75em] w-[0.75em] shrink-0 opacity-60" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="max-h-96 w-80 overflow-y-auto p-2"
        aria-label={t("picker.label")}
      >
        {calendars.length === 0 ? (
          <p className="px-2 py-1.5 text-muted-foreground text-sm">{t("panel.noCalendars")}</p>
        ) : (
          <ul className="space-y-0.5">
            <li className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-accent">
              <Checkbox
                id={allId}
                checked={allShown ? true : shown.length > 0 ? "indeterminate" : false}
                onCheckedChange={onShowAll}
              />
              <Label htmlFor={allId} className="min-w-0 flex-1 cursor-pointer font-medium text-sm">
                {t("picker.all")}
              </Label>
            </li>
            {calendars.map((calendar) => (
              <CalendarRow
                key={`${calendar.community_id}-${calendar.id}`}
                calendar={calendar}
                shown={!isCalendarHidden(calendar)}
                unread={unread.hasResource(calendar.community_id, Tool.calendar, calendar.id)}
                onToggle={() => onToggleCalendar(calendar)}
                settingsPathFor={settingsPathFor}
                className="px-2 py-1.5 hover:bg-accent"
              />
            ))}
          </ul>
        )}
        {canCreate ? (
          <Button
            variant="ghost"
            size="sm"
            className="mt-1 h-8 w-full justify-start gap-2 px-2 font-normal text-muted-foreground hover:text-foreground"
            onClick={onCreate}
          >
            <Plus className="h-4 w-4" />
            {t("createCalendar")}
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
};

/** The calendar list panel behind a toolbar dropdown: a "Calendars" trigger
 * opening the visibility panel, so the calendar grid keeps the full page
 * width. The trigger carries how many calendars are switched off, so a
 * narrowed grid still says so with the panel shut. */
export const CalendarPanelDropdown = (props: ComponentProps<typeof CalendarListPanel>) => {
  const { t } = useTranslation("calendars");
  // Counted from the same predicates the rows render from, so the badge and
  // the checkboxes can never disagree.
  const hiddenCount =
    props.calendars.filter(props.isCalendarHidden).length +
    props.projectCalendars.filter(props.isProjectHidden).length;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant={hiddenCount > 0 ? "secondary" : "outline"} size="sm" className="h-9">
          <CalendarDays className="h-4 w-4" />
          {t("panel.calendars")}
          {hiddenCount > 0 ? (
            <>
              <span
                aria-hidden="true"
                className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 font-medium text-2xs text-primary-foreground tabular-nums"
              >
                {hiddenCount}
              </span>
              <span className="sr-only">{t("panel.hiddenCount", { count: hiddenCount })}</span>
            </>
          ) : null}
          <ChevronDown className="h-4 w-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-h-96 w-80 overflow-y-auto">
        <CalendarListPanel {...props} />
      </PopoverContent>
    </Popover>
  );
};

/** The calendar page's list panel — real calendars (color, visibility,
 * settings link) and one read-only task calendar per project, Google-Calendar
 * style. Sharing/rename/delete live on each calendar's settings page. */
export const CalendarListPanel = ({
  calendars,
  projectCalendars,
  isCalendarHidden,
  isProjectHidden,
  onToggleCalendar,
  onToggleProject,
  calendarLabel,
  settingsPathFor,
}: CalendarListPanelProps) => {
  const { t } = useTranslation("calendars");
  const unread = useUnreadTree();

  return (
    <div className="space-y-4">
      <section className="space-y-1">
        <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
          {t("panel.calendars")}
        </h2>
        {calendars.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("panel.noCalendars")}</p>
        ) : (
          <ul className="space-y-0.5">
            {calendars.map((calendar) => (
              <CalendarRow
                key={`${calendar.community_id}-${calendar.id}`}
                calendar={calendar}
                label={calendarLabel?.(calendar)}
                shown={!isCalendarHidden(calendar)}
                unread={unread.hasResource(calendar.community_id, Tool.calendar, calendar.id)}
                onToggle={() => onToggleCalendar(calendar)}
                settingsPathFor={settingsPathFor}
                className="px-1 py-0.5"
              />
            ))}
          </ul>
        )}
      </section>

      {projectCalendars.length > 0 && (
        <section className="space-y-1">
          <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
            {t("panel.projectTasks")}
          </h2>
          <ProjectTaskToggles
            projects={projectCalendars}
            isProjectHidden={isProjectHidden}
            onToggleProject={onToggleProject}
            className="space-y-0.5"
          />
        </section>
      )}
    </div>
  );
};
