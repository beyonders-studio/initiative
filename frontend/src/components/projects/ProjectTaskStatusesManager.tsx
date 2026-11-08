/**
 * A project's task statuses: the columns its tasks move through, each in a
 * category and with its own icon and colour. A new status is added from the
 * form above the table, and a deleted one's tasks move to the status the
 * reader picks, or the project's default.
 */

import type { IconName } from "lucide-react/dynamic";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  TaskStatusCategory,
  TaskStatusRead,
  TaskStatusUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { byPosition, DefinitionTable } from "@/components/projects/DefinitionTable";
import {
  useCreateTaskStatus,
  useDeleteTaskStatus,
  useProjectTaskStatuses,
  useReorderTaskStatuses,
  useUpdateTaskStatus,
} from "@/hooks/useProjects";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { defaultsForCategory, maybeSwapDefaultsOnCategoryChange } from "@/lib/taskStatusDefaults";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { IconPicker } from "@/ui/icon-picker";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const CATEGORY_VALUES: TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

// The fallback select's "let the project decide" row. Radix needs a real value,
// and the API takes the absence of one as the same instruction.
const FALLBACK_AUTO = "auto";

interface ProjectTaskStatusesManagerProps {
  projectId: number;
  canManage: boolean;
}

export const ProjectTaskStatusesManager = ({
  projectId,
  canManage,
}: ProjectTaskStatusesManagerProps) => {
  const { t } = useTranslation(["projects", "common"]);

  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<TaskStatusCategory>("todo");
  const newCategoryDefaults = defaultsForCategory("todo");
  const [newColor, setNewColor] = useState<string>(newCategoryDefaults.color);
  const [newIcon, setNewIcon] = useState<IconName>(newCategoryDefaults.icon);
  const [deleteTarget, setDeleteTarget] = useState<TaskStatusRead | null>(null);
  const [fallbackId, setFallbackId] = useState<string>(FALLBACK_AUTO);

  const statusesQuery = useProjectTaskStatuses(projectId);
  const reorderStatuses = useReorderTaskStatuses(projectId);
  // A task shows its status's name, category and look, so the tasks read anew.
  const updateStatus = useUpdateTaskStatus(projectId, {
    onSuccess: () => void invalidate(q.allTasks()),
  });

  const createStatus = useCreateTaskStatus(projectId, {
    onSuccess: () => {
      setNewName("");
      toast.success(t("statuses.created"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:statuses.createError"));
    },
  });

  const deleteStatusMutation = useDeleteTaskStatus(projectId, {
    onSuccess: () => {
      toast.success(t("statuses.deleted"));
      setFallbackId(FALLBACK_AUTO);
      setDeleteTarget(null);
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:statuses.deleteError"));
    },
  });

  const handleNewCategoryChange = (nextCategory: TaskStatusCategory) => {
    const swapped = maybeSwapDefaultsOnCategoryChange(newCategory, nextCategory, newColor, newIcon);
    setNewCategory(nextCategory);
    setNewColor(swapped.color);
    setNewIcon(swapped.icon);
  };

  const handleDeleteConfirm = () => {
    if (!deleteTarget) {
      return;
    }
    const fallback = fallbackId === FALLBACK_AUTO ? null : Number(fallbackId);
    deleteStatusMutation.mutate({
      statusId: deleteTarget.id,
      // Null hands the choice to the server, which moves any stranded tasks to
      // the project's default column.
      data: { fallback_status_id: Number.isFinite(fallback) ? fallback : null },
    });
  };

  // Any other column will do — a status being retired often has no sibling in
  // its own category, which is what used to make it undeletable.
  const fallbackOptions = deleteTarget
    ? byPosition(statusesQuery.data ?? []).filter((status) => status.id !== deleteTarget.id)
    : [];
  const isOnlyStatus = Boolean(deleteTarget) && fallbackOptions.length === 0;

  const categoryItems = (
    <SelectContent>
      {CATEGORY_VALUES.map((value) => (
        <SelectItem key={value} value={value}>
          {t(
            `statuses.category${value.charAt(0).toUpperCase()}${value.slice(1).replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())}` as `statuses.categoryBacklog`
          )}
        </SelectItem>
      ))}
    </SelectContent>
  );

  return (
    <>
      <DefinitionTable
        keys="statuses"
        rows={statusesQuery.data}
        loading={statusesQuery.isLoading || statusesQuery.isRefetching}
        canManage={canManage}
        reorder={reorderStatuses}
        onUpdate={(statusId, data) =>
          updateStatus.mutateAsync({ statusId, data: data as TaskStatusUpdate })
        }
        saving={updateStatus.isPending}
        onDelete={(status) => {
          setDeleteTarget(status);
          setFallbackId(FALLBACK_AUTO);
        }}
        column={{
          head: t("statuses.categoryColumn"),
          cell: (status, edit) => (
            <Select
              value={status.category}
              onValueChange={(value) => {
                const category = value as TaskStatusCategory;
                edit({
                  category,
                  ...maybeSwapDefaultsOnCategoryChange(
                    status.category,
                    category,
                    status.color,
                    status.icon
                  ),
                });
              }}
              disabled={!canManage}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              {categoryItems}
            </Select>
          ),
        }}
      >
        <div className="space-y-4">
          <h4 className="font-semibold text-sm">{t("statuses.addStatus")}</h4>
          <div className="flex flex-wrap items-end gap-3">
            <Input
              className="max-w-xs"
              placeholder={t("statuses.statusNamePlaceholder")}
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              disabled={!canManage || createStatus.isPending}
            />
            <Select
              value={newCategory}
              onValueChange={(value) => handleNewCategoryChange(value as TaskStatusCategory)}
              disabled={!canManage || createStatus.isPending}
            >
              <SelectTrigger className="w-48">
                <SelectValue placeholder={t("statuses.selectCategory")} />
              </SelectTrigger>
              {categoryItems}
            </Select>
            <IconPicker
              value={newIcon}
              onValueChange={(icon) => setNewIcon(icon)}
              triggerPlaceholder={t("statuses.iconPlaceholder")}
              disabled={!canManage || createStatus.isPending}
            />
            <ColorPickerPopover
              className="w-40"
              value={newColor}
              onChangeComplete={(hex) => setNewColor(hex)}
              disabled={!canManage || createStatus.isPending}
              triggerLabel={t("statuses.colorPlaceholder")}
            />
            <Button
              onClick={() => {
                const trimmedName = newName.trim();
                if (!trimmedName) {
                  return;
                }
                createStatus.mutate({
                  name: trimmedName,
                  category: newCategory,
                  is_default: false,
                  color: newColor,
                  icon: newIcon,
                });
              }}
              disabled={!canManage}
              pending={createStatus.isPending}
            >
              {t("statuses.add")}
            </Button>
          </div>
        </div>
      </DefinitionTable>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("statuses.deleteTitle")}</DialogTitle>
            <DialogDescription>
              {t("statuses.deleteDescription", { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          {isOnlyStatus ? (
            <p className="text-muted-foreground text-sm">{t("statuses.onlyStatus")}</p>
          ) : (
            <Field label={t("statuses.fallbackLabel")}>
              <Select value={fallbackId} onValueChange={setFallbackId}>
                <SelectTrigger>
                  <SelectValue placeholder={t("statuses.chooseFallback")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FALLBACK_AUTO}>{t("statuses.fallbackAuto")}</SelectItem>
                  {fallbackOptions.map((option) => (
                    <SelectItem key={option.id} value={String(option.id)}>
                      {option.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          <DialogFooter
            submitLabel={t("common:delete")}
            onSubmit={handleDeleteConfirm}
            pending={deleteStatusMutation.isPending}
            disabled={isOnlyStatus}
            destructive
          />
        </DialogContent>
      </Dialog>
    </>
  );
};
