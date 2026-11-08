import { ChevronLeft, ChevronRight, Columns3, UserMinus, UserPlus } from "lucide-react";
import { createContext, useContext, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskListRead, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { TaskStatusOption } from "@/components/tasks/TaskStatusOption";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateTaskInCommunity } from "@/hooks/useTasks";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/ui/dropdown-menu";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

import { TaskAssigneeStack } from "./TaskAssigneeList";

/** What a board offers its cards' menus: its columns, and moving a task
 *  between them as dropping it in one would. */
export type BoardActions = {
  statuses: TaskStatusRead[];
  moveTo: (taskId: number, taskStatusId: number) => void;
  /** Whether the column takes one more task. */
  isFull: (taskStatusId: number) => boolean;
};

export const BoardActionsContext = createContext<BoardActions | null>(null);

/**
 * Putting yourself on a task, or taking yourself off it, without opening it.
 * The server applies it to whoever is on the task when it lands, so someone
 * added since this view loaded stays on it.
 */
const useAssignMe = (task: TaskListRead) => {
  const { t } = useTranslation("projects");
  const { user } = useAuth();
  const activeCommunityId = useActiveCommunityId();
  const update = useUpdateTaskInCommunity(undefined, "projects:quickActions.assignError");
  const assigned = user ? task.assignees.some((assignee) => assignee.id === user.id) : false;
  const change = (assign: boolean) => {
    if (!user) return;
    update.mutate(
      {
        communityId: task.community_id ?? activeCommunityId,
        taskId: task.id,
        data: assign ? { add_assignee_ids: [user.id] } : { remove_assignee_ids: [user.id] },
      },
      {
        onSuccess: () =>
          toast.success(t(assign ? "quickActions.assigned" : "quickActions.unassigned")),
      }
    );
  };
  return { canAssign: user !== null, assigned, change, pending: update.isPending };
};

/** A table's assignees cell: who is on the task, or, where nobody is and the
 *  reader may change it, a button to take it. */
export const TaskAssigneesCell = ({ task, canEdit }: { task: TaskListRead; canEdit: boolean }) => {
  if (task.assignees.length > 0) {
    return <TaskAssigneeStack assignees={task.assignees} />;
  }
  return canEdit ? (
    <AssignMeButton task={task} />
  ) : (
    <span className="text-muted-foreground text-sm">&mdash;</span>
  );
};

const AssignMeButton = ({ task }: { task: TaskListRead }) => {
  const { t } = useTranslation("projects");
  const { canAssign, change, pending } = useAssignMe(task);
  if (!canAssign) return null;
  // An empty avatar's place, quiet until it is pointed at.
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-6 rounded-full border border-muted-foreground/40 border-dashed text-muted-foreground hover:border-solid hover:text-foreground"
            disabled={pending}
            onClick={() => change(true)}
            aria-label={t("quickActions.assignToMeFor", { title: task.title })}
          >
            <UserPlus className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t("quickActions.assignToMe")}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

/** The menu beside a card's title on a board its reader may change. Moving
 *  it is what a drag does, for a finger or a keyboard that can't drag. */
export const TaskCardActions = ({ item: task }: { item: TaskListRead }) => {
  const { t } = useTranslation(["projects", "common"]);
  const board = useContext(BoardActionsContext);
  const { canAssign, assigned, change, pending } = useAssignMe(task);
  // A fly-out needs room beside the menu to land in, which a card in a
  // phone's column hasn't: there the menu becomes the list of columns, with a
  // row back out, as the account menu does.
  const isMobile = !atLeast(useWidthClass(), "md");
  const [choosingColumn, setChoosingColumn] = useState(false);
  const canMove = board !== null && board.statuses.length > 1;

  const columns = board ? (
    <DropdownMenuRadioGroup
      value={String(task.task_status_id)}
      onValueChange={(value) => {
        const statusId = Number(value);
        if (statusId !== task.task_status_id) board.moveTo(task.id, statusId);
      }}
    >
      {board.statuses.map((status) => {
        const full = status.id !== task.task_status_id && board.isFull(status.id);
        return (
          <DropdownMenuRadioItem key={status.id} value={String(status.id)} disabled={full}>
            <TaskStatusOption status={status} />
            {full ? (
              <span className="ml-auto text-muted-foreground text-xs">{t("kanban.full")}</span>
            ) : null}
          </DropdownMenuRadioItem>
        );
      })}
    </DropdownMenuRadioGroup>
  ) : null;

  return (
    <RowActionsMenu
      subject={task.title}
      className="-mt-1.5 -mr-1.5 shrink-0"
      onOpenChange={(open) => {
        if (open) setChoosingColumn(false);
      }}
    >
      {choosingColumn && canMove ? (
        <>
          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              setChoosingColumn(false);
            }}
          >
            <ChevronLeft />
            {t("common:back")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>{t("quickActions.moveTo")}</DropdownMenuLabel>
          {columns}
        </>
      ) : null}
      {!choosingColumn && canAssign ? (
        <DropdownMenuItem disabled={pending} onSelect={() => change(!assigned)}>
          {assigned ? <UserMinus /> : <UserPlus />}
          {t(assigned ? "quickActions.unassignMe" : "quickActions.assignToMe")}
        </DropdownMenuItem>
      ) : null}
      {!choosingColumn && canMove && isMobile ? (
        <DropdownMenuItem
          onSelect={(event) => {
            event.preventDefault();
            setChoosingColumn(true);
          }}
        >
          <Columns3 />
          {t("quickActions.moveTo")}
          <ChevronRight className="ml-auto" />
        </DropdownMenuItem>
      ) : null}
      {!choosingColumn && canMove && !isMobile ? (
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <Columns3 />
            {t("quickActions.moveTo")}
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>{columns}</DropdownMenuSubContent>
        </DropdownMenuSub>
      ) : null}
    </RowActionsMenu>
  );
};
