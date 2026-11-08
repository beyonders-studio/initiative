/**
 * A project's task types: the kinds of task it holds (a task, a bug, an idea),
 * each with its own icon, colour and page. Every project starts with four, and
 * always keeps at least one; one of them is the default a new task takes.
 *
 * Drawn in the table task statuses use too: drafts saved together, drag to
 * reorder, and a dialog asking where a deleted type's tasks go. A type's page
 * is changed in the project's layout editor, which "Edit page" opens on it.
 * A type is added from the ready-made ones, blank, or from one the project has;
 * types are copied from another project; and each says what a new task of it
 * starts with.
 */

import { Link } from "@tanstack/react-router";
import { Copy, ListPlus, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type TaskTypeCreated,
  type TaskTypeRead,
  type TaskTypeStartingValues,
  type TaskTypeUpdate,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { byPosition, DefinitionTable } from "@/components/projects/DefinitionTable";
import { TaskTypeAddDialog } from "@/components/projects/TaskTypeAddDialog";
import { TaskTypeCopyDialog } from "@/components/projects/TaskTypeCopyDialog";
import { TaskTypeDeleteDialog } from "@/components/projects/TaskTypeDeleteDialog";
import {
  startsWithSomething,
  TaskTypeStartsWithDialog,
} from "@/components/projects/TaskTypeStartsWithDialog";
import {
  useCopyTaskTypes,
  useCreateTaskType,
  usePlaceTaskTypeFields,
  useProjectTaskTypes,
  useReorderTaskTypes,
  useUpdateTaskType,
} from "@/hooks/useProjects";
import { useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { atLeast, useWidthClass } from "@/ui/lib/useWidthClass";

/** The most types a project may have; the server holds it to the same. */
export const MAX_TASK_TYPES = 20;

/** The `?layout=` value that opens the layout editor on one type's page. */
export const taskTypeLayout = (typeId: number): string => `task:${typeId}`;

interface ProjectTaskTypesManagerProps {
  projectId: number;
  initiativeId: number;
  canManage: boolean;
}

export const ProjectTaskTypesManager = ({
  projectId,
  initiativeId,
  canManage,
}: ProjectTaskTypesManagerProps) => {
  const { t } = useTranslation(["projects", "common", "errors"]);
  const gp = useCommunityPath();
  // The layout editor needs a tablet-sized screen, and a step above write
  // access, which the project's layouts say.
  const wide = atLeast(useWidthClass(), "md");
  const canConfigurePages =
    useInstanceLayouts(Tool.project, projectId).data?.can_configure ?? false;
  const editor = gp(`${toolDetailRoute(Tool.project, initiativeId, projectId)}/layouts`);

  const [addOpen, setAddOpen] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [startsWithTarget, setStartsWithTarget] = useState<TaskTypeRead | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const typesQuery = useProjectTaskTypes(projectId);
  const reorderTypes = useReorderTaskTypes(projectId);
  const updateType = useUpdateTaskType(projectId);

  const placeTypeFields = usePlaceTaskTypeFields(projectId);
  /** A ready-made type's fields, placed on its page. The type stands whether
   *  or not this does. */
  const placeFields = (created: TaskTypeCreated) =>
    placeTypeFields(created).catch(() =>
      toast.warning(t("taskTypes.gallery.fieldsNotPlaced", { name: created.name }))
    );

  const createType = useCreateTaskType(projectId, {
    onSuccess: (created) => {
      setAddOpen(false);
      toast.success(t("taskTypes.created"));
      if (created.field_ids.length > 0) {
        void placeFields(created);
      }
    },
  });

  const saveStartsWith = useUpdateTaskType(
    projectId,
    {
      onSuccess: () => {
        setStartsWithTarget(null);
        toast.success(t("taskTypes.startsWith.saved"));
      },
    },
    "projects:taskTypes.updateError"
  );

  const copyTypes = useCopyTaskTypes(projectId, {
    onSuccess: (copied) => {
      setCopyOpen(false);
      toast.success(t("taskTypes.copy.copied", { count: copied.length }));
    },
  });

  const types = byPosition(typesQuery.data ?? []);
  const atLimit = types.length >= MAX_TASK_TYPES;

  const handleStartsWith = (values: TaskTypeStartingValues | null) => {
    if (!startsWithTarget) return;
    saveStartsWith.mutate({
      typeId: startsWithTarget.id,
      data: { starting_values: values },
    });
  };

  return (
    <>
      <DefinitionTable
        keys="taskTypes"
        rows={typesQuery.data}
        loading={typesQuery.isLoading || typesQuery.isRefetching}
        canManage={canManage}
        reorder={reorderTypes}
        onUpdate={(typeId, data) =>
          updateType.mutateAsync({ typeId, data: data as TaskTypeUpdate })
        }
        saving={updateType.isPending}
        onDelete={(type) => setDeleteTarget(type.id)}
        rowActions={(type) => (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="relative"
              onClick={() => setStartsWithTarget(type)}
              disabled={!canManage}
              aria-label={t("taskTypes.startsWith.openFor", { name: type.name })}
              title={
                startsWithSomething(type.starting_values)
                  ? t("taskTypes.startsWith.hasValues")
                  : undefined
              }
            >
              <ListPlus className="h-4 w-4" />
              {startsWithSomething(type.starting_values) ? (
                <span
                  aria-hidden="true"
                  className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-primary"
                />
              ) : null}
            </Button>
            {canConfigurePages && wide ? (
              <Button asChild variant="ghost" size="sm">
                <Link
                  to={editor}
                  search={{ layout: taskTypeLayout(type.id) }}
                  aria-label={t("taskTypes.editPageFor", { name: type.name })}
                >
                  <Pencil className="h-4 w-4" />
                  {t("taskTypes.editPage")}
                </Link>
              </Button>
            ) : null}
          </>
        )}
        toolbar={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCopyOpen(true)}
              disabled={atLimit}
            >
              <Copy className="h-4 w-4" />
              {t("taskTypes.copy.open")}
            </Button>
            <Button size="sm" onClick={() => setAddOpen(true)} disabled={atLimit}>
              <Plus className="h-4 w-4" />
              {t("taskTypes.addType")}
            </Button>
          </>
        }
        notes={
          <>
            {canManage && atLimit ? (
              <p className="text-muted-foreground text-sm">
                {t("taskTypes.limitReached", { max: MAX_TASK_TYPES })}
              </p>
            ) : null}
            {/* The editor says so itself too, but a row's missing button would
                otherwise be unexplained. */}
            {canConfigurePages && !wide ? (
              <p className="text-muted-foreground text-sm">{t("taskTypes.pagesOnWiderScreen")}</p>
            ) : null}
          </>
        }
      />

      <TaskTypeAddDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        projectId={projectId}
        types={types}
        saving={createType.isPending}
        onAdd={(data) => createType.mutate(data)}
      />

      <TaskTypeCopyDialog
        open={copyOpen}
        onOpenChange={setCopyOpen}
        projectId={projectId}
        types={types}
        room={Math.max(0, MAX_TASK_TYPES - types.length)}
        saving={copyTypes.isPending}
        onCopy={(sourceProjectId, typeIds) =>
          copyTypes.mutate({ source_project_id: sourceProjectId, type_ids: typeIds })
        }
      />

      <TaskTypeStartsWithDialog
        type={startsWithTarget}
        saving={saveStartsWith.isPending}
        onOpenChange={(open) => !open && setStartsWithTarget(null)}
        onSave={handleStartsWith}
      />

      <TaskTypeDeleteDialog
        projectId={projectId}
        typeId={deleteTarget}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
};
