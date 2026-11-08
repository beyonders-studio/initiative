/**
 * Deleting a task type: where its tasks go, the project's default unless the
 * reader picks another. A project keeps at least one type, so its last one
 * says so instead.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { byPosition } from "@/components/projects/DefinitionTable";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { useDeleteTaskType, useProjectTaskTypes } from "@/hooks/useProjects";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** Where a deleted type's tasks go unless the reader picks another: the
 *  project's default, or, when the default is the one going, the first type
 *  left. */
const defaultFallback = (others: TaskTypeRead[]): number | null =>
  (others.find((type) => type.is_default) ?? others[0])?.id ?? null;

export const TaskTypeDeleteDialog = ({
  projectId,
  typeId,
  onClose,
}: {
  projectId: number;
  /** The type being deleted; null keeps the dialog closed. */
  typeId: number | null;
  onClose: () => void;
}) => {
  const { t } = useTranslation(["projects", "common"]);
  const types = useProjectTaskTypes(projectId, { enabled: typeId !== null }).data;
  const target = types?.find((type) => type.id === typeId);
  const others = useMemo(
    () => byPosition((types ?? []).filter((type) => type.id !== typeId)),
    [types, typeId]
  );
  // The reader's pick holds for the type it was made for.
  const [picked, setPicked] = useState<{ typeId: number; value: string } | null>(null);
  const fallbackId =
    picked && picked.typeId === typeId ? picked.value : String(defaultFallback(others) ?? "");
  const isOnlyType = target !== undefined && others.length === 0;

  const deleteType = useDeleteTaskType(projectId, {
    onSuccess: () => {
      toast.success(t("taskTypes.deleted"));
      onClose();
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:taskTypes.deleteError"));
    },
  });

  return (
    <Dialog open={typeId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("taskTypes.deleteTitle")}</DialogTitle>
          <DialogDescription>
            {t("taskTypes.deleteDescription", { name: target?.name })}
          </DialogDescription>
        </DialogHeader>
        {isOnlyType ? (
          <p className="text-muted-foreground text-sm">{t("taskTypes.onlyType")}</p>
        ) : (
          <Field label={t("taskTypes.fallbackLabel")}>
            <Select
              value={fallbackId}
              onValueChange={(value) => typeId !== null && setPicked({ typeId, value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {others.map((option) => (
                  <SelectItem key={option.id} value={String(option.id)}>
                    <TaskTypeOption type={option} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        <DialogFooter
          submitLabel={t("common:delete")}
          onSubmit={() =>
            target &&
            deleteType.mutate({
              typeId: target.id,
              data: { fallback_type_id: Number(fallbackId) },
            })
          }
          pending={deleteType.isPending}
          disabled={!target || isOnlyType || !fallbackId}
          destructive
        />
      </DialogContent>
    </Dialog>
  );
};
