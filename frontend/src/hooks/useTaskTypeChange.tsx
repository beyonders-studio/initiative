import { useTranslation } from "react-i18next";

import { type TaskUpdate, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useFillRequired } from "@/components/layouts/FillRequiredDialog";
import { useProjectTaskTypes } from "@/hooks/useProjects";
import { useReadTaskNow } from "@/hooks/useTasks";
import { detailLayoutOf, instanceTarget, useToolLayouts } from "@/hooks/useToolLayouts";
import { requiredKeys, type StoredRegions } from "@/lib/layouts/detailLayout";
import {
  TASK_DETAIL,
  taskChanges,
  taskFillContext,
  useMissingAsType,
} from "@/lib/layouts/taskLayout";

/**
 * A task of `projectId` given another type from a list, as a drop into
 * another type's group does: `change` sends it at once where the type's page
 * requires nothing the task leaves empty, and otherwise asks for that first
 * (`dialog`) and sends it with the change.
 */
export const useTaskTypeChange = (projectId: number, initiativeId: number | null) => {
  const { t } = useTranslation("layouts");
  const missingAs = useMissingAsType(projectId, initiativeId);
  const fill = useFillRequired(TASK_DETAIL);
  const readTask = useReadTaskNow();
  const types = useProjectTaskTypes(projectId).data;
  const layouts = useToolLayouts(instanceTarget(Tool.project, projectId)).data;
  /** Whether the type's page requires anything at all: a change to one that
   *  does waits for the task to be read. */
  const requires = (typeId: number) =>
    requiredKeys(detailLayoutOf(layouts, "task", typeId) as StoredRegions | null).length > 0;
  const change = async (
    taskId: number,
    typeId: number,
    send: (changes: TaskUpdate) => Promise<unknown>
  ) => {
    // Unread, the server is what holds it to the page.
    const task = await readTask(taskId).catch(() => null);
    const keys = task ? missingAs(task, typeId) : [];
    if (!task || keys.length === 0) {
      await send({});
      return;
    }
    const type = types?.find((each) => each.id === typeId);
    fill.ask({
      item: { ...task, task_type_id: typeId, ...(type ? { task_type: type } : {}) },
      context: taskFillContext(initiativeId),
      keys,
      title: t("required.retypeTitle", { type: type?.name ?? "" }),
      send: (written) => send(taskChanges(written)),
    });
  };
  return { requires, change, dialog: fill.dialog };
};
