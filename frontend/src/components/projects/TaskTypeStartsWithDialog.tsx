/**
 * What a new task of a type starts with, where whoever makes it leaves a field
 * empty: a description outline, checklist lines, a priority and a repeat. The
 * server fills them in; this is where a project says what they are.
 */

import { ArrowDown, ArrowUp, Loader2, Plus, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskPriority,
  TaskTypeRead,
  TaskTypeStartingValues,
} from "@/api/generated/initiativeAPI.schemas";
import { RecurrenceEditor } from "@/components/recurrence/RecurrenceEditor";
import { TaskPriorityOption } from "@/components/tasks/TaskPriorityOption";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { fromStored, type TaskRecurrenceValue, toRRule } from "@/lib/recurrence";
import { PRIORITY_ORDER } from "@/lib/sorting";

const NO_PRIORITY = "none";

/** Whether a type starts a task with anything at all. */
export const startsWithSomething = (values: TaskTypeStartingValues | null | undefined): boolean =>
  Boolean(
    values &&
      (values.description || values.checklist?.length || values.priority || values.recurrence)
  );

type Draft = {
  description: string;
  checklist: string[];
  priority: TaskPriority | null;
  repeat: TaskRecurrenceValue;
};

const draftOf = (values: TaskTypeStartingValues | null | undefined): Draft => {
  const strategy = values?.recurrence_strategy ?? "fixed";
  return {
    description: values?.description ?? "",
    checklist: values?.checklist ?? [],
    priority: values?.priority ?? null,
    repeat: {
      rule: fromStored(values?.recurrence, null, 0, false, strategy === "rolling"),
      strategy,
      limit: null,
    },
  };
};

/** The draft as sent: null where it starts nothing. */
const valuesOf = (
  draft: Draft,
  stored: TaskTypeStartingValues | null | undefined
): TaskTypeStartingValues | null => {
  const { rule, strategy } = draft.repeat;
  const recurrence =
    rule === null ? null : rule === "custom" ? (stored?.recurrence ?? null) : toRRule(rule);
  const values: TaskTypeStartingValues = {
    description: draft.description.trim() ? draft.description : null,
    checklist: draft.checklist.map((line) => line.trim()).filter(Boolean),
    priority: draft.priority,
    recurrence,
    recurrence_strategy: recurrence ? strategy : null,
  };
  return startsWithSomething(values) ? values : null;
};

interface TaskTypeStartsWithDialogProps {
  type: TaskTypeRead | null;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (values: TaskTypeStartingValues | null) => void;
}

export const TaskTypeStartsWithDialog = ({
  type,
  saving,
  onOpenChange,
  onSave,
}: TaskTypeStartsWithDialogProps) => {
  const { t } = useTranslation(["projects", "tasks", "common"]);
  const [draft, setDraft] = useState<Draft>(() => draftOf(type?.starting_values));

  // Each type opened starts from what it holds.
  const [prevType, setPrevType] = useState(type);
  if (prevType !== type) {
    setPrevType(type);
    if (type) setDraft(draftOf(type.starting_values));
  }

  const setLine = (index: number, value: string) =>
    setDraft((prev) => ({
      ...prev,
      checklist: prev.checklist.map((line, at) => (at === index ? value : line)),
    }));
  const moveLine = (index: number, by: -1 | 1) =>
    setDraft((prev) => {
      const next = [...prev.checklist];
      [next[index], next[index + by]] = [next[index + by], next[index]];
      return { ...prev, checklist: next };
    });
  const removeLine = (index: number) =>
    setDraft((prev) => ({
      ...prev,
      checklist: prev.checklist.filter((_, at) => at !== index),
    }));

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSave(valuesOf(draft, type?.starting_values));
  };

  return (
    <Dialog open={type !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto bg-card">
        <form onSubmit={handleSubmit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("taskTypes.startsWith.title", { name: type?.name })}</DialogTitle>
            <DialogDescription>{t("taskTypes.startsWith.description")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="starts-with-description">
              {t("taskTypes.startsWith.descriptionLabel")}
            </Label>
            <Textarea
              id="starts-with-description"
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              placeholder={t("taskTypes.startsWith.descriptionPlaceholder")}
              rows={5}
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="font-medium text-sm">
              {t("taskTypes.startsWith.checklistLabel")}
            </legend>
            {draft.checklist.map((line, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: lines are edited in place
              <div key={index} className="flex items-center gap-1">
                <Input
                  value={line}
                  onChange={(event) => setLine(index, event.target.value)}
                  maxLength={2000}
                  aria-label={t("taskTypes.startsWith.lineLabel", { number: index + 1 })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => moveLine(index, -1)}
                  disabled={index === 0}
                  aria-label={t("taskTypes.startsWith.moveUp")}
                >
                  <ArrowUp className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => moveLine(index, 1)}
                  disabled={index === draft.checklist.length - 1}
                  aria-label={t("taskTypes.startsWith.moveDown")}
                >
                  <ArrowDown className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeLine(index)}
                  aria-label={t("taskTypes.startsWith.removeLine")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setDraft({ ...draft, checklist: [...draft.checklist, ""] })}
              disabled={draft.checklist.length >= 50}
            >
              <Plus className="h-4 w-4" />
              {t("taskTypes.startsWith.addLine")}
            </Button>
          </fieldset>

          <div className="space-y-2">
            <Label htmlFor="starts-with-priority">{t("taskTypes.startsWith.priorityLabel")}</Label>
            <Select
              value={draft.priority ?? NO_PRIORITY}
              onValueChange={(value) =>
                setDraft({
                  ...draft,
                  priority: value === NO_PRIORITY ? null : (value as TaskPriority),
                })
              }
            >
              <SelectTrigger id="starts-with-priority">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PRIORITY}>{t("taskTypes.startsWith.noPriority")}</SelectItem>
                {PRIORITY_ORDER.map((option) => (
                  <SelectItem key={option} value={option}>
                    <TaskPriorityOption priority={option} label={t(`tasks:priority.${option}`)} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <RecurrenceEditor
              kind="task"
              value={draft.repeat.rule}
              onChange={(rule) => setDraft({ ...draft, repeat: { ...draft.repeat, rule } })}
              strategy={draft.repeat.strategy}
              limit={null}
              onTaskChange={(repeat) => setDraft({ ...draft, repeat })}
            />
            <p className="text-muted-foreground text-xs">{t("taskTypes.startsWith.repeatHint")}</p>
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("common:save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
