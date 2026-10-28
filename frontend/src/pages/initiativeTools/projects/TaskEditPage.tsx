import { useParams, useRouter } from "@tanstack/react-router";
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Copy,
  FolderInput,
  Loader2,
  MoreHorizontal,
  SkipForward,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { ContentKind, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getReadTaskQueryKey, readTask } from "@/api/generated/tasks/tasks";
import { invalidate, q } from "@/api/query-keys";
import { useFillRequired } from "@/components/layouts/FillRequiredDialog";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { useScopePrompt } from "@/components/recurrence/OccurrenceScopeDialog";
import { StatusMessage } from "@/components/StatusMessage";
import { SubscribeButton } from "@/components/SubscribeButton";
import { TaskEditSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { MoveTaskDialog } from "@/components/tasks/MoveTaskDialog";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useAuth } from "@/hooks/useAuth";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useColumnLimits } from "@/hooks/useColumnLimits";
import { useCommunities } from "@/hooks/useCommunities";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import {
  useProject,
  useProjectTaskStatuses,
  useProjectTaskTypes,
  useWritableProjects,
} from "@/hooks/useProjects";
import {
  useDeleteTask,
  useDuplicateTask,
  useMoveTask,
  useSkipTask,
  useTask,
} from "@/hooks/useTasks";
import { detailLayoutOf, useInstanceLayouts } from "@/hooks/useToolLayouts";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage, getHttpStatus, requiredKeysIn } from "@/lib/errorMessage";
import { DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import { usePluginMenuActions } from "@/lib/layouts/plugins";
import { TASK_DETAIL, taskChanges, taskFillContext } from "@/lib/layouts/taskLayout";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import { taskRoute, toolDetailRoute, toolListRoute } from "@/lib/tools";

type MoveTaskVariables = {
  targetProjectId: number;
  targetProjectName?: string;
  previousProjectId: number | null;
};

export const TaskEditPage = () => {
  const { taskId, projectId: projectIdParam } = useParams({ strict: false }) as {
    taskId: string;
    projectId?: string;
  };
  const parsedTaskId = Number(taskId);
  const router = useRouter();
  const communityId = useActiveCommunityId();
  const { user: currentUser } = useAuth();
  useCommunities();
  const { t } = useTranslation(["tasks", "common", "layouts"]);
  const gp = useCommunityPath();

  // Set by the delete, which leaves a page a description draft would hold.
  const leavingRef = useRef(false);
  const [isMoveDialogOpen, setIsMoveDialogOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [moveContext, setMoveContext] = useState<MoveTaskVariables | null>(null);

  const taskQuery = useTask(parsedTaskId);
  useReadOnOpen("task", taskQuery.data?.id);
  useRecordOpen("task", taskQuery.data?.id);

  const projectId = projectIdParam ? Number(projectIdParam) : taskQuery.data?.project_id;
  const projectQuery = useProject(projectId ?? null);
  // Where a delete returns to. Held in a ref because a task opened without a
  // project in its path resolves its project through the task query, and the
  // delete clears that before the success handler navigates. The task's own
  // project wins over the one in the path: moving the task rewrites the former
  // and leaves the latter behind.
  const lastProjectIdRef = useRef<number | null>(null);
  const taskProjectId = taskQuery.data?.project_id;
  const columnLimits = useColumnLimits(taskProjectId ?? null);
  useEffect(() => {
    const owner = typeof taskProjectId === "number" ? taskProjectId : projectId;
    if (typeof owner === "number" && Number.isFinite(owner)) {
      lastProjectIdRef.current = owner;
    }
  }, [taskProjectId, projectId]);

  const taskStatusesQuery = useProjectTaskStatuses(projectId ?? null);
  const taskTypesQuery = useProjectTaskTypes(projectId ?? null);
  // The task's project's layouts say how its detail is laid out, and a move
  // takes the detail to its new project's. A set that cannot be read draws
  // the detail as shipped.
  const layoutsQuery = useInstanceLayouts(Tool.project, taskProjectId ?? null);
  const task = taskQuery.data;
  const showTask = (shown: TaskRead) =>
    queryClient.setQueryData<TaskRead>(getReadTaskQueryKey(communityId, parsedTaskId), shown);

  const isProjectContextLoading =
    Number.isFinite(projectId) && projectQuery.isLoading && !projectQuery.data;

  const duplicateTask = useDuplicateTask({
    onSuccess: (newTask) => {
      toast.success(t("edit.taskDuplicated"));
      router.navigate({
        to: gp(taskRoute(initiativeId, newTask.project_id, newTask.id)),
      });
    },
  });

  const scopePrompt = useScopePrompt();
  const repeating = Boolean(task?.recurrence);
  // A plug-in's actions are the plug-in's to allow, so a reader who cannot
  // edit the task may still run them.
  const pluginActions = usePluginMenuActions(
    "task",
    parsedTaskId,
    projectQuery.data?.initiative_id
  );

  const skipTask = useSkipTask({
    onSuccess: (skipped) => {
      showTask(skipped);
      toast.success(t("edit.taskSkipped"));
    },
  });

  const deleteTask = useDeleteTask({
    onSuccess: async (_data, { scope }) => {
      // Deleting just this one of a series skips it, so the task is still
      // here, unless it was the series' last and is gone.
      if (scope === "this") {
        try {
          showTask(await readTask(communityId, parsedTaskId));
          toast.success(t("edit.taskSkipped"));
          return;
        } catch (error) {
          if (getHttpStatus(error) !== 404) {
            toast.success(t("edit.taskSkipped"));
            return;
          }
        }
      }
      toast.success(t("edit.taskDeleted"));
      leavingRef.current = true;
      // Back to the project the task lived in — the projects list is a step
      // further out than the user asked to go.
      const returnProjectId = lastProjectIdRef.current;
      router.navigate({
        to: gp(
          returnProjectId === null
            ? toolListRoute(Tool.project, initiativeId)
            : toolDetailRoute(Tool.project, initiativeId, returnProjectId)
        ),
      });
    },
  });

  // A move its page in the destination refuses for what the task leaves
  // empty asks for that, and is sent again with it.
  const fillForMove = useFillRequired(TASK_DETAIL);
  const moveTask = useMoveTask({
    onError: (error, { taskId, targetProjectId }) => {
      const keys = requiredKeysIn(error);
      const target = writableProjects.find((each) => each.id === targetProjectId);
      if (!keys || !task || !target) {
        toast.error(getErrorMessage(error, "tasks:edit.moveError"));
        return;
      }
      setIsMoveDialogOpen(false);
      fillForMove.ask({
        item: { ...task, project_id: target.id },
        context: taskFillContext(target.initiative_id),
        keys,
        title: t("layouts:required.moveTitle", { project: target.name }),
        send: (written) =>
          moveTask.mutateAsync({ taskId, targetProjectId, changes: taskChanges(written) }),
      });
    },
    onSuccess: (updatedTask) => {
      showTask(updatedTask);
      const previousProjectId = moveContext?.previousProjectId;
      if (typeof previousProjectId === "number") {
        void invalidate(q.projectTaskStatuses(previousProjectId), q.project(previousProjectId));
      }
      if (typeof moveContext?.targetProjectId === "number") {
        void invalidate(
          q.projectTaskStatuses(moveContext.targetProjectId),
          q.project(moveContext.targetProjectId)
        );
      }
      setIsMoveDialogOpen(false);
      toast.success(
        t("edit.moveSuccess", {
          projectName: moveContext?.targetProjectName ?? "the selected project",
        })
      );
      setMoveContext(null);
    },
  });

  const archiveTask = useArchiveEntity({
    onSuccess: () => toast.success(t("edit.taskArchived")),
  });
  const unarchiveTask = useUnarchiveEntity({
    onSuccess: () => toast.success(t("edit.taskUnarchived")),
  });
  const toggleArchive = task?.archived_at !== null ? unarchiveTask : archiveTask;

  const handleDelete = async () => {
    if (!repeating) {
      setShowDeleteConfirm(true);
      return;
    }
    const scope = await scopePrompt.ask("delete", { tool: "tasks", count: task?.series_size });
    if (scope !== null) {
      deleteTask.mutate({ taskId: parsedTaskId, scope });
    }
  };

  const handleMoveTask = (targetProjectId: number) => {
    if (moveTask.isPending || !task) {
      return;
    }
    const targetProject = writableProjects.find((project) => project.id === targetProjectId);
    const context: MoveTaskVariables = {
      targetProjectId,
      targetProjectName: targetProject?.name,
      previousProjectId: task.project_id ?? null,
    };
    setMoveContext(context);
    moveTask.mutate({
      taskId: parsedTaskId,
      targetProjectId,
    });
  };

  const project = projectQuery.data;
  // A task's initiative is its project's. The path supplies it while that
  // loads, and a URL naming a different one is corrected in place.
  const initiativeId = useCanonicalInitiativeId(project?.initiative_id);

  // Pure DAC: permissions inherited from project. Server-computed — already
  // capped at "read" when the community's content is frozen (read_only status).
  const canWriteProject = Boolean(project?.can.edit);
  const projectIsArchived = (project?.archived_at ?? null) !== null;
  const isReadOnly = !canWriteProject || projectIsArchived;
  const readOnlyMessage = !canWriteProject
    ? t("edit.readOnlyNoAccess")
    : projectIsArchived
      ? t("edit.readOnlyArchived")
      : null;

  const writableProjectsQuery = useWritableProjects({
    enabled: Boolean(canWriteProject && !projectIsArchived),
  });
  // An initiative that keeps its content in keeps its tasks.
  const initiativeQuery = useInitiative(project?.initiative_id ?? null);
  const keptIn = initiativeQuery.data?.keep_content_in;
  const writableProjects = useMemo(
    () =>
      (writableProjectsQuery.data?.items ?? []).filter(
        (candidate) => !keptIn || candidate.initiative_id === project?.initiative_id
      ),
    [writableProjectsQuery.data, keptIn, project?.initiative_id]
  );

  if (
    taskQuery.isLoading ||
    isProjectContextLoading ||
    taskStatusesQuery.isLoading ||
    layoutsQuery.isLoading
  ) {
    return <TaskEditSkeleton label={t("edit.loadingTask")} />;
  }

  if (taskQuery.isError || taskStatusesQuery.isError || !task) {
    return (
      <ToolAccessStatus
        error={taskQuery.error ?? taskStatusesQuery.error}
        keys="tasks:edit."
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("edit.backToProjects")}
        entity={{ kind: "task", id: parsedTaskId }}
      />
    );
  }

  if (Number.isFinite(projectId) && projectQuery.isError) {
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={t("edit.loadProjectError")}
        backTo={gp(toolListRoute(Tool.project, initiativeId))}
        backLabel={t("edit.backToProjects")}
      />
    );
  }

  // Delete and move are excluded: their confirm/move dialogs stay open and
  // already show the mutation's own loading state.
  const menuActionPending =
    duplicateTask.isPending || toggleArchive.isPending || skipTask.isPending;

  // Everything a task supports beyond its fields lives behind the overflow
  // menu, so the header stays readable at any width.
  const menu =
    isReadOnly && pluginActions.items.length === 0 ? null : (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          {/* Duplicate and archive dismiss the menu that holds their own pending
            label, and neither opens a dialog to carry one, so the trigger
            reports their progress instead. */}
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={t("common:toolbar.moreActions")}
            aria-busy={menuActionPending}
          >
            {menuActionPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MoreHorizontal className="h-4 w-4" />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {isReadOnly ? null : (
            <>
              <DropdownMenuItem
                disabled={moveTask.isPending}
                onSelect={() => setIsMoveDialogOpen(true)}
              >
                <FolderInput className="h-4 w-4" />
                {t("edit.moveToProject")}
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={duplicateTask.isPending}
                onSelect={() => duplicateTask.mutate(parsedTaskId)}
              >
                <Copy className="h-4 w-4" />
                {duplicateTask.isPending ? t("edit.duplicating") : t("edit.duplicateTask")}
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={toggleArchive.isPending}
                onSelect={() =>
                  toggleArchive.mutate({ entityType: "task", entityId: parsedTaskId })
                }
              >
                {task.archived_at !== null ? (
                  <>
                    <ArchiveRestore className="h-4 w-4" />
                    {toggleArchive.isPending ? t("edit.unarchiving") : t("edit.unarchive")}
                  </>
                ) : (
                  <>
                    <Archive className="h-4 w-4" />
                    {toggleArchive.isPending ? t("edit.archiving") : t("edit.archive")}
                  </>
                )}
              </DropdownMenuItem>
              {repeating ? (
                <DropdownMenuItem
                  disabled={skipTask.isPending}
                  onSelect={() => skipTask.mutate(parsedTaskId)}
                >
                  <SkipForward className="h-4 w-4" />
                  {t("edit.skipOccurrence")}
                </DropdownMenuItem>
              ) : null}
            </>
          )}
          {!isReadOnly && pluginActions.items.length > 0 ? <DropdownMenuSeparator /> : null}
          {pluginActions.items}
          {isReadOnly ? null : (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                disabled={deleteTask.isPending}
                onSelect={() => void handleDelete()}
              >
                <Trash2 className="h-4 w-4" />
                {deleteTask.isPending ? t("edit.deleting") : t("edit.deleteTask")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  // A moderator's shield sits beside the menu rather than in it: a moderator
  // who may not edit the task has no menu, and still moderates it.
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);
  // Subscribing needs nothing but read, so the actions are always there.
  const actions = (
    <div className="flex items-center gap-1">
      <SubscribeButton kind={ContentKind.task} entityId={parsedTaskId} />
      <ModerationMenu
        targetType="task"
        targetId={parsedTaskId}
        canModerate={canModerate}
        onGone={() => {
          leavingRef.current = true;
          const returnProjectId = lastProjectIdRef.current;
          router.navigate({
            to: gp(
              returnProjectId === null
                ? toolListRoute(Tool.project, initiativeId)
                : toolDetailRoute(Tool.project, initiativeId, returnProjectId)
            ),
          });
        }}
      />
      {menu}
    </div>
  );

  return (
    <div className="space-y-6">
      <ToolBreadcrumb
        tool={Tool.project}
        initiativeId={initiativeId}
        trail={
          project
            ? [{ label: project.name, to: toolDetailRoute(Tool.project, initiativeId, project.id) }]
            : []
        }
      />
      <DetailLayoutView
        detail={TASK_DETAIL}
        item={task}
        layout={
          detailLayoutOf(layoutsQuery.data, "task", task.task_type_id) as StoredRegions | null
        }
        context={{
          readOnly: isReadOnly,
          readOnlyMessage,
          statuses: taskStatusesQuery.data ?? [],
          types: taskTypesQuery.data ?? [],
          isFull: columnLimits.isFull,
          initiativeId: project?.initiative_id ?? null,
          currentUserId: currentUser?.id,
          askScope: scopePrompt.ask,
          actions,
          leaving: leavingRef,
        }}
      />

      {pluginActions.dialog}
      {fillForMove.dialog}
      <MoveTaskDialog
        open={isMoveDialogOpen}
        onOpenChange={setIsMoveDialogOpen}
        projects={writableProjects}
        currentProjectId={task.project_id}
        isLoading={writableProjectsQuery.isLoading || initiativeQuery.isLoading}
        hasError={Boolean(writableProjectsQuery.isError)}
        isSaving={moveTask.isPending}
        onConfirm={handleMoveTask}
      />

      {scopePrompt.dialog}

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("edit.deleteTitle")}
        description={t("edit.deleteDescription")}
        confirmLabel={t("common:delete")}
        onConfirm={() => {
          deleteTask.mutate({ taskId: parsedTaskId });
          setShowDeleteConfirm(false);
        }}
        isLoading={deleteTask.isPending}
        destructive
      />
    </div>
  );
};
