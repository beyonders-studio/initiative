import { Link } from "@tanstack/react-router";
import { ChevronDown, Crosshair, Pin, PinOff, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import { DateCell } from "@/components/tasks/TaskDateCell";
import { NO_TASK_COLUMN_LIMITS, type TaskColumnLimits } from "@/hooks/useColumnLimits";
import { FOCUS_HORIZON_ANY, FOCUS_PRIORITIES, type useFocusSummary } from "@/hooks/useFocusSummary";
import { communityPath } from "@/lib/communityUrl";
import { entityRefRoute, taskRoute } from "@/lib/tools";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader } from "@/ui/card";
import { Checkbox } from "@/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/ui/collapsible";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";
import { Progress } from "@/ui/progress";
import { Separator } from "@/ui/separator";
import { Slider } from "@/ui/slider";
import { StatusMessage } from "@/ui/status-message";
import { TooltipProvider } from "@/ui/tooltip";

type FocusSummaryData = ReturnType<typeof useFocusSummary>;

export type FocusSummaryProps = {
  focus: FocusSummaryData;
  activeCommunityId: number | null;
  /** Reused from the page's table so status resolution has one implementation. */
  changeTaskStatus: (task: TaskListRead, category: TaskStatusCategory) => Promise<void>;
  /** Whether THIS task has a status change in flight, so one row saving leaves
   *  the rest of the section usable. */
  isUpdatingTask: (task: TaskListRead) => boolean;
  /** Which of the tasks' projects' columns are full. */
  columnLimits?: TaskColumnLimits;
  /** Fill a home page tile on the grid: always open, its list scrolling inside
   *  the tile. The tile is what the reader sizes there, so there is nothing to
   *  fold; stacked on a narrow screen, it folds as usual. */
  fill?: boolean;
};

const taskHref = (task: TaskListRead, activeCommunityId: number | null) => {
  const communityId = task.community_id ?? activeCommunityId;
  // A task's URL names its project and initiative; a row missing either
  // resolves through `/go` rather than pointing at an address that isn't one.
  const path =
    task.initiative_id != null
      ? taskRoute(task.initiative_id, task.project_id, task.id)
      : entityRefRoute("task", task.id);
  return communityId ? communityPath(communityId, path) : path;
};

type FocusRowProps = {
  task: TaskListRead;
  activeCommunityId: number | null;
  isPinned: boolean;
  onTogglePin: () => void;
  onToggleDone: () => void;
  disabled: boolean;
  /** The full column checking it would put the task in, which disables it. */
  full?: string;
  done?: boolean;
};

const FocusRow = ({
  task,
  activeCommunityId,
  isPinned,
  onTogglePin,
  onToggleDone,
  disabled,
  full,
  done = false,
}: FocusRowProps) => {
  const { t } = useTranslation(["tasks", "common", "projects"]);
  const context = [task.project_name, task.community_name].filter(Boolean).join(" · ");

  return (
    <div className="group flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-muted/50">
      <Checkbox
        checked={done}
        disabled={disabled || full !== undefined}
        title={full === undefined ? undefined : t("projects:kanban.statusFull", { name: full })}
        onCheckedChange={() => onToggleDone()}
        aria-label={done ? t("checkbox.markInProgress") : t("checkbox.markDone")}
      />
      <div className="min-w-0 flex-1">
        <Link
          to={taskHref(task, activeCommunityId)}
          className={cn(
            "block truncate font-medium text-sm hover:underline",
            done && "text-muted-foreground"
          )}
        >
          {task.title}
        </Link>
        {context ? <p className="truncate text-muted-foreground text-xs">{context}</p> : null}
      </div>
      {!done && task.due_date ? (
        <div className="hidden shrink-0 text-xs sm:block">
          <DateCell date={task.due_date} isPastVariant="destructive" />
        </div>
      ) : null}
      <Button
        variant="ghost"
        size="sm"
        className={cn(
          "h-7 w-7 shrink-0 p-0",
          !isPinned && "opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
        )}
        onClick={onTogglePin}
        aria-label={isPinned ? t("focus.unpin") : t("focus.pin")}
        title={isPinned ? t("focus.unpin") : t("focus.pin")}
      >
        {isPinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
};

const FocusSettings = ({ focus }: { focus: FocusSummaryData }) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { prefs, setHorizon } = focus;

  /** What a slider stop means, in words: the same value the leg is built from. */
  const horizonLabel = (days: number) => {
    if (days >= FOCUS_HORIZON_ANY) return t("focus.horizon.any");
    if (days === 0) return t("focus.horizon.today");
    return t("focus.horizon.days", { count: days });
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" aria-label={t("focus.settings")}>
          <Settings2 className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-4 sm:w-80">
        <div className="space-y-1">
          <Label className="text-xs">{t("focus.horizonsLabel")}</Label>
          <p className="text-muted-foreground text-xs">{t("focus.horizonsHint")}</p>
        </div>

        <div className="space-y-4">
          {FOCUS_PRIORITIES.map((priority) => {
            const days = prefs.horizons[priority];
            const label = t(`priority.${priority}`);
            return (
              <div key={priority} className="space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <Label className="text-xs capitalize">{label}</Label>
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {horizonLabel(days)}
                  </span>
                </div>
                <Slider
                  value={[days]}
                  min={0}
                  max={FOCUS_HORIZON_ANY}
                  step={1}
                  thumbLabel={label}
                  onValueChange={([next]) => setHorizon(priority, next)}
                  // The whole track is draggable, so the padding is what makes
                  // it a finger-sized target rather than a 4px line.
                  className="py-1.5"
                />
              </div>
            );
          })}
        </div>

        <p className="text-muted-foreground text-xs">{t("focus.settingsHint")}</p>
      </PopoverContent>
    </Popover>
  );
};

/**
 * A short, capped list of what needs doing now, above the full task table.
 *
 * Deliberately not a second view of the table below it: it holds only what the
 * rules match plus what the user pinned, and it keeps today's completions
 * visible rather than dropping them the moment they're checked, so finishing
 * work reads as progress instead of disappearance.
 */
export const FocusSummary = ({
  focus,
  activeCommunityId,
  changeTaskStatus,
  isUpdatingTask,
  columnLimits = NO_TASK_COLUMN_LIMITS,
  fill = false,
}: FocusSummaryProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const { pinned, upcoming, completedToday, truncated, doneCount, totalCount, prefs } = focus;

  const progress = totalCount > 0 ? (doneCount / totalCount) * 100 : 0;
  const open = fill || prefs.open;

  const renderRow = (task: TaskListRead, done: boolean) => (
    <FocusRow
      key={`${task.community_id ?? "none"}:${task.id}`}
      task={task}
      activeCommunityId={activeCommunityId}
      isPinned={focus.isPinned(task)}
      onTogglePin={() => focus.togglePin(task)}
      onToggleDone={() => void changeTaskStatus(task, done ? "in_progress" : "done")}
      disabled={isUpdatingTask(task)}
      full={columnLimits.fullFor(task, done ? "in_progress" : "done")?.name}
      done={done}
    />
  );

  return (
    // The app shell supplies a tooltip context, but the section carries its own
    // so the date cells inside it work wherever it is mounted.
    <TooltipProvider delayDuration={300}>
      <Card className={cn(fill && "flex h-full min-h-0 flex-col overflow-hidden")}>
        <Collapsible
          open={open}
          onOpenChange={(next) => focus.setPreference("open", next)}
          className={cn(fill && "flex min-h-0 flex-1 flex-col")}
        >
          <CardHeader
            className={cn(
              "flex flex-row items-center justify-between space-y-0 py-3",
              fill && "min-h-12 border-b px-4 py-2"
            )}
          >
            <div className="flex min-w-0 items-center gap-3">
              {fill ? (
                <h2 className="flex items-center gap-2 font-semibold text-base">
                  <Crosshair className="size-4 text-muted-foreground" aria-hidden="true" />
                  {t("focus.title")}
                </h2>
              ) : (
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="-ml-2 h-8 gap-2 px-2">
                    <ChevronDown
                      className={cn("h-4 w-4 transition-transform", !open && "-rotate-90")}
                    />
                    <span className="font-semibold text-base">{t("focus.title")}</span>
                  </Button>
                </CollapsibleTrigger>
              )}
              {totalCount > 0 ? (
                <Badge variant="secondary" className="shrink-0">
                  {t("focus.progress", { done: doneCount, total: totalCount })}
                </Badge>
              ) : null}
            </div>
            <FocusSettings focus={focus} />
          </CardHeader>

          <CollapsibleContent className={cn(fill && "min-h-0 flex-1 overflow-auto")}>
            <CardContent className={cn("pt-0 pb-4", fill && "px-4 pt-3")}>
              {totalCount > 0 ? <Progress value={progress} className="mb-3 h-1" /> : null}

              {focus.hasError ? (
                <StatusMessage />
              ) : focus.isEmpty ? (
                <p className="py-4 text-center text-muted-foreground text-sm">{t("focus.empty")}</p>
              ) : (
                <div className="space-y-0.5">
                  {pinned.map((task) => renderRow(task, false))}
                  {upcoming.map((task) => renderRow(task, false))}

                  {truncated ? (
                    <p className="px-2 pt-1 text-muted-foreground text-xs">
                      {t("focus.truncated", { shown: upcoming.length })}
                    </p>
                  ) : null}

                  {completedToday.length > 0 ? (
                    <>
                      <Separator className="my-2" />
                      {completedToday.map((task) => renderRow(task, true))}
                    </>
                  ) : null}
                </div>
              )}
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </TooltipProvider>
  );
};
