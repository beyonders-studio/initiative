import { Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  RecurrenceStrategy,
  TaskListRead,
  TaskPriority,
  TaskStatusRead,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { MemberMultiSelect } from "@/components/members/MemberSearchSelect";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useListedMissingAsType } from "@/lib/layouts/taskLayout";
import {
  isHourlyRule,
  isValidTaskRecurrence,
  rulePayload,
  type TaskRecurrenceValue,
} from "@/lib/recurrence";
import { PRIORITY_ORDER } from "@/lib/sorting";

/** The type option that takes a picked type back: the tasks keep theirs. */
const KEEP_TYPE = "keep";

export type TaskBulkUpdate = {
  start_date: string | null;
  due_date: string | null;
  assignee_ids: number[];
  task_status_id: number;
  task_type_id: number;
  priority: TaskPriority;
  recurrence: string | null;
  /** The zone the rule's days are in; each task's rule is stored from its own start. */
  tz: string;
  recurrence_strategy: RecurrenceStrategy;
  recurrence_limit: number | null;
};

interface TaskBulkEditDialogProps {
  selectedTasks: TaskListRead[];
  taskStatuses: TaskStatusRead[];
  /** The project's task types. One alone is not offered: it tells nothing apart. */
  taskTypes: TaskTypeRead[];
  /** Whether a column takes every selected task not already in it. */
  isFull?: (taskStatusId: number) => boolean;
  projectId: number;
  initiativeId: number;
  isSubmitting: boolean;
  onApply: (changes: Partial<TaskBulkUpdate>) => void;
  onCancel: () => void;
}

export const TaskBulkEditDialog = ({
  selectedTasks,
  taskStatuses,
  taskTypes,
  isFull,
  projectId,
  initiativeId,
  isSubmitting,
  onApply,
  onCancel,
}: TaskBulkEditDialogProps) => {
  const { t } = useTranslation(["tasks", "common", "projects"]);
  const { user: currentUser } = useAuth();
  const [startDate, setStartDate] = useState<string>("");
  const [dueDate, setDueDate] = useState<string>("");
  const [assigneeIds, setAssigneeIds] = useState<number[]>([]);
  const [statusId, setStatusId] = useState<string>("");
  const [typeId, setTypeId] = useState<string>("");
  const [priority, setPriority] = useState<string>("");
  const [repeat, setRepeat] = useState<TaskRecurrenceValue>({
    rule: null,
    strategy: "fixed",
    limit: null,
  });
  const { rule: recurrence, strategy: recurrenceStrategy, limit } = repeat;
  const hasDueDate = Boolean(dueDate) || selectedTasks.every((task) => Boolean(task.due_date));
  const typeCheck = useListedMissingAsType(projectId, initiativeId);
  // What else this edit fills counts toward what the new type's page requires.
  const filling = {
    ...(startDate ? { start_date: startDate } : {}),
    ...(dueDate ? { due_date: dueDate } : {}),
    ...(assigneeIds.length > 0 ? { assignee_ids: assigneeIds } : {}),
    ...(recurrence ? rulePayload(recurrence) : {}),
  };
  /** How many of the tasks the type's page requires something of that they
   *  leave empty: the server refuses each, so the type isn't offered. */
  const leavingEmpty = (id: number) =>
    selectedTasks.filter(
      (task) => task.task_type_id !== id && typeCheck.missing(task, id, filling).length > 0
    ).length;
  // Until the type's page is read, the server may take some tasks and not others.
  const typeBlocked = typeId !== "" && (!typeCheck.ready || leavingEmpty(Number(typeId)) > 0);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const changes: Partial<TaskBulkUpdate> = {};

    if (startDate) {
      changes.start_date = new Date(startDate).toISOString();
    }

    if (dueDate) {
      changes.due_date = new Date(dueDate).toISOString();
    }

    if (assigneeIds.length > 0) {
      changes.assignee_ids = assigneeIds;
    }

    if (statusId) {
      changes.task_status_id = Number(statusId);
    }

    if (typeId) {
      if (typeBlocked) return;
      changes.task_type_id = Number(typeId);
    }

    if (priority) {
      changes.priority = priority as TaskPriority;
    }

    if (recurrence) {
      if (!isValidTaskRecurrence(repeat) || (isHourlyRule(recurrence) && !hasDueDate)) return;
      Object.assign(changes, rulePayload(recurrence));
      changes.recurrence_strategy = recurrenceStrategy;
      changes.recurrence_limit = limit;
    }

    if (Object.keys(changes).length > 0) {
      onApply(changes);
    }
  };

  const hasChanges =
    startDate || dueDate || assigneeIds.length > 0 || statusId || typeId || priority || recurrence;

  return (
    <DialogContent className="bg-card">
      <DialogHeader>
        <DialogTitle>{t("bulkEdit.title")}</DialogTitle>
        <DialogDescription>
          {t("bulkEdit.description", { count: selectedTasks.length })}
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={handleSubmit}>
        <Accordion type="single" collapsible className="w-full">
          <AccordionItem value="dates">
            <AccordionTrigger>{t("bulkEdit.datesSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label htmlFor="bulk-start-date">{t("bulkEdit.startDateLabel")}</Label>
                <DateTimePicker
                  value={startDate}
                  onChange={setStartDate}
                  placeholder={t("bulkEdit.startDatePlaceholder")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bulk-due-date">{t("bulkEdit.dueDateLabel")}</Label>
                <DateTimePicker
                  value={dueDate}
                  onChange={setDueDate}
                  placeholder={t("bulkEdit.dueDatePlaceholder")}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="assignment">
            <AccordionTrigger>{t("bulkEdit.assignmentSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>{t("bulkEdit.assigneesLabel")}</Label>
                <MemberMultiSelect
                  scope={{ type: "canOpen", tool: Tool.project, id: projectId }}
                  selectedIds={assigneeIds}
                  onChange={setAssigneeIds}
                  emptyMessage={t("bulkEdit.noUsersAvailable")}
                  currentUserId={currentUser?.id}
                />
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="details">
            <AccordionTrigger>{t("bulkEdit.detailsSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              {taskTypes.length > 1 ? (
                <div className="space-y-2">
                  <Label htmlFor="bulk-type">{t("bulkEdit.typeLabel")}</Label>
                  <Select
                    value={typeId}
                    onValueChange={(value) => setTypeId(value === KEEP_TYPE ? "" : value)}
                    disabled={!typeCheck.ready}
                  >
                    <SelectTrigger id="bulk-type">
                      <SelectValue placeholder={t("bulkEdit.selectType")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={KEEP_TYPE}>{t("bulkEdit.keepType")}</SelectItem>
                      {taskTypes.map((type) => {
                        const count = leavingEmpty(type.id);
                        return (
                          <SelectItem key={type.id} value={String(type.id)} disabled={count > 0}>
                            <TaskTypeOption
                              type={
                                count > 0
                                  ? {
                                      ...type,
                                      name: t("bulkEdit.typeLeavesEmpty", {
                                        name: type.name,
                                        count,
                                      }),
                                    }
                                  : type
                              }
                            />
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="bulk-status">{t("bulkEdit.statusLabel")}</Label>
                <Select value={statusId} onValueChange={setStatusId}>
                  <SelectTrigger id="bulk-status">
                    <SelectValue placeholder={t("bulkEdit.selectStatus")} />
                  </SelectTrigger>
                  <SelectContent>
                    {taskStatuses.map((status) => {
                      const full = isFull?.(status.id) === true;
                      return (
                        <SelectItem key={status.id} value={String(status.id)} disabled={full}>
                          {full
                            ? t("projects:kanban.statusFull", { name: status.name })
                            : status.name}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="bulk-priority">{t("bulkEdit.priorityLabel")}</Label>
                <Select value={priority} onValueChange={setPriority}>
                  <SelectTrigger id="bulk-priority">
                    <SelectValue placeholder={t("bulkEdit.selectPriority")} />
                  </SelectTrigger>
                  <SelectContent>
                    {PRIORITY_ORDER.map((option) => (
                      <SelectItem key={option} value={option}>
                        <TaskPriorityOption priority={option} label={t(`priority.${option}`)} />
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="recurrence">
            <AccordionTrigger>{t("bulkEdit.recurrenceSection")}</AccordionTrigger>
            <AccordionContent className="space-y-4 pb-4">
              <div className="space-y-2">
                <Label>{t("bulkEdit.recurringSchedule")}</Label>
                <RecurrenceEditor
                  kind="task"
                  value={recurrence}
                  onChange={(rule) => setRepeat({ ...repeat, rule })}
                  strategy={recurrenceStrategy}
                  limit={limit}
                  onTaskChange={setRepeat}
                  hasDueDate={hasDueDate}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <DialogFooter className="mt-6">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={isSubmitting}>
            {t("common:cancel")}
          </Button>
          <Button type="submit" disabled={!hasChanges || typeBlocked || isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("bulkEdit.applying")}
              </>
            ) : (
              t("bulkEdit.applyChanges")
            )}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
};
