import { BellRing } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import { useTaskReminder } from "@/hooks/usePersonalItems";
import { fromPickerValue, toPickerValue } from "@/lib/localDateTime";

/**
 * When to remind the reader of a task: theirs alone, kept beside what else they
 * keep about it, and told to them as subscription news. A repeating task's next
 * one takes the reminder at the same distance from its due date, as its start
 * date is.
 */
export const TaskReminderField = ({
  task,
}: {
  task: Pick<TaskRead, "id" | "recurrence" | "due_date">;
}) => {
  const { t } = useTranslation(["tasks", "common"]);
  const reminder = useTaskReminder(task.id);
  const value = toPickerValue(reminder.remindAt);
  const sent =
    reminder.remindedAt !== null &&
    reminder.remindAt !== null &&
    new Date(reminder.remindAt).getTime() <= Date.now();
  const note = sent
    ? t("reminder.sent")
    : task.recurrence && task.due_date && reminder.remindAt
      ? t("reminder.repeats")
      : t("reminder.private");
  return (
    <div className="space-y-2">
      <Label
        htmlFor="task-reminder"
        className="inline-flex items-center gap-1.5 font-normal text-muted-foreground text-xs"
      >
        <BellRing className="size-3.5" aria-hidden="true" />
        {t("reminder.label")}
      </Label>
      <DateTimePicker
        id="task-reminder"
        value={value}
        onChange={(next) => {
          if (next !== value) reminder.set(fromPickerValue(next));
        }}
        disabled={!reminder.ready}
        placeholder={t("reminder.placeholder")}
        clearLabel={t("reminder.clear")}
      />
      <p className="text-muted-foreground text-xs">{note}</p>
    </div>
  );
};
