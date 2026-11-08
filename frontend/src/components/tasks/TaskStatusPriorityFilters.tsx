import { useTranslation } from "react-i18next";

import { type TaskPriority, TaskStatusCategory } from "@/api/generated/initiativeAPI.schemas";
import { PRIORITY_ORDER } from "@/lib/sorting";
import { Label } from "@/ui/label";
import { MultiSelect } from "@/ui/multi-select";

interface TaskStatusPriorityFiltersProps {
  statusFilters: TaskStatusCategory[];
  onStatusChange: (next: TaskStatusCategory[]) => void;
  priorityFilters: TaskPriority[];
  onPriorityChange: (next: TaskPriority[]) => void;
}

/** The status-category and priority pickers of a task filter panel. */
export const TaskStatusPriorityFilters = ({
  statusFilters,
  onStatusChange,
  priorityFilters,
  onPriorityChange,
}: TaskStatusPriorityFiltersProps) => {
  const { t } = useTranslation("tasks");
  return (
    <>
      <div className="w-full sm:w-48 md:flex-1">
        <Label className="mb-2 block font-medium text-muted-foreground text-xs">
          {t("filters.filterByStatusCategory")}
        </Label>
        <MultiSelect
          selectedValues={statusFilters}
          options={Object.values(TaskStatusCategory).map((category) => ({
            value: category,
            label: t(`statusCategory.${category}`),
          }))}
          onChange={(values) => onStatusChange(values as TaskStatusCategory[])}
          placeholder={t("filters.allStatusCategories")}
          emptyMessage={t("filters.noStatusCategories")}
        />
      </div>
      <div className="w-full sm:w-48 md:flex-1">
        <Label className="mb-2 block font-medium text-muted-foreground text-xs">
          {t("filters.filterByPriority")}
        </Label>
        <MultiSelect
          selectedValues={priorityFilters}
          options={PRIORITY_ORDER.map((priority) => ({
            value: priority,
            label: t(`priority.${priority}` as never),
          }))}
          onChange={(values) => onPriorityChange(values as TaskPriority[])}
          placeholder={t("filters.allPriorities")}
          emptyMessage={t("filters.noPriorities")}
        />
      </div>
    </>
  );
};
