import { Archive, Pencil, Tags, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { TaskListRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { SelectionBar } from "@/ui/selection-bar";

import { type ExportParams, ExportTasksButton } from "./ExportTasksButton";

type TaskBulkEditPanelProps = {
  selectedTasks: TaskListRead[];
  onEdit: () => void;
  onEditTags: () => void;
  onArchive: () => void;
  onDelete: () => void;
  isArchiving?: boolean;
  /** When set, an "Export Selected" action renders ahead of the edit
   * actions, exporting exactly this selector (an ``id in_`` condition). */
  exportParams?: ExportParams;
};

export const TaskBulkEditPanel = ({
  selectedTasks,
  onEdit,
  onEditTags,
  onArchive,
  onDelete,
  isArchiving,
  exportParams,
}: TaskBulkEditPanelProps) => {
  const { t } = useTranslation(["tasks", "common", "exports"]);
  return (
    <SelectionBar label={t("bulkEdit.selected", { count: selectedTasks.length })}>
      {exportParams && (
        <ExportTasksButton params={exportParams} label={t("exports:export.selected")} />
      )}
      <Button variant="outline" size="sm" onClick={onEditTags}>
        <Tags className="h-4 w-4" />
        {t("bulkEdit.editTags")}
      </Button>
      <Button variant="outline" size="sm" onClick={onEdit}>
        <Pencil className="h-4 w-4" />
        {t("common:edit")}
      </Button>
      <Button variant="outline" size="sm" onClick={onArchive} disabled={isArchiving}>
        <Archive className="h-4 w-4" />
        {isArchiving ? t("edit.archiving") : t("edit.archive")}
      </Button>
      <Button variant="destructive" size="sm" onClick={onDelete}>
        <Trash2 className="h-4 w-4" />
        {t("common:delete")}
      </Button>
    </SelectionBar>
  );
};
