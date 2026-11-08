import {
  DndContext,
  type DragEndEvent,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { TFunction } from "i18next";
import { GripVertical, Loader2, Save, Trash2 } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskStatusCategory, TaskStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
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
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { Checkbox } from "@/ui/checkbox";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { IconPicker } from "@/ui/icon-picker";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

const CATEGORY_VALUES: TaskStatusCategory[] = ["backlog", "todo", "in_progress", "done"];

// The fallback select's "let the project decide" row. Radix needs a real value,
// and the API takes the absence of one as the same instruction.
const FALLBACK_AUTO = "auto";

const sortStatuses = (items: TaskStatusRead[]): TaskStatusRead[] => {
  return [...items].sort((a, b) => {
    if (a.position === b.position) {
      return a.id - b.id;
    }
    return a.position - b.position;
  });
};

interface ProjectTaskStatusesManagerProps {
  projectId: number;
  canManage: boolean;
}

export const ProjectTaskStatusesManager = ({
  projectId,
  canManage,
}: ProjectTaskStatusesManagerProps) => {
  const { t } = useTranslation(["projects", "common"]);

  const categoryOptions = useMemo(
    () =>
      CATEGORY_VALUES.map((value) => ({
        value,
        label: t(
          `statuses.category${value.charAt(0).toUpperCase()}${value.slice(1).replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())}` as `statuses.categoryBacklog`
        ),
      })),
    [t]
  );

  const [orderedStatuses, setOrderedStatuses] = useState<TaskStatusRead[]>([]);
  const [drafts, setDrafts] = useState<
    Record<number, { name: string; category: TaskStatusCategory; color: string; icon: IconName }>
  >({});
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<TaskStatusCategory>("todo");
  const newCategoryDefaults = defaultsForCategory("todo");
  const [newColor, setNewColor] = useState<string>(newCategoryDefaults.color);
  const [newIcon, setNewIcon] = useState<IconName>(newCategoryDefaults.icon);
  const [deleteTarget, setDeleteTarget] = useState<TaskStatusRead | null>(null);
  const [fallbackId, setFallbackId] = useState<string>(FALLBACK_AUTO);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 8,
      },
    })
  );

  const statusesQuery = useProjectTaskStatuses(projectId);

  const reorderStatuses = useReorderTaskStatuses(projectId, {
    onSuccess: (data) => {
      const sorted = sortStatuses(data);
      setOrderedStatuses(sorted);
      toast.success(t("statuses.orderSaved"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:statuses.reorderError"));
    },
  });

  useEffect(() => {
    if (!statusesQuery.data || reorderStatuses.isPending) {
      return;
    }
    const sorted = sortStatuses(statusesQuery.data);
    setOrderedStatuses(sorted);
    const nextDrafts: Record<
      number,
      { name: string; category: TaskStatusCategory; color: string; icon: IconName }
    > = {};
    sorted.forEach((status) => {
      nextDrafts[status.id] = {
        name: status.name,
        category: status.category,
        color: status.color,
        icon: status.icon as IconName,
      };
    });
    setDrafts(nextDrafts);
  }, [statusesQuery.data, reorderStatuses.isPending]);

  const createStatus = useCreateTaskStatus(projectId, {
    onSuccess: () => {
      setNewName("");
      toast.success(t("statuses.created"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:statuses.createError"));
    },
  });

  const updateStatus = useUpdateTaskStatus(projectId, {
    onSuccess: () => {
      toast.success(t("statuses.updated"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "projects:statuses.updateError"));
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

  // Separate instance for bulk updates in handleSaveAll to avoid conflicting
  // with the single-status updateStatus callbacks (toast messages differ).
  const bulkUpdateStatus = useUpdateTaskStatus(projectId);

  const defaultStatusId = useMemo(() => {
    return orderedStatuses.find((status) => status.is_default)?.id ?? null;
  }, [orderedStatuses]);

  const handleDragEnd = (event: DragEndEvent) => {
    if (!canManage) {
      return;
    }
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    setOrderedStatuses((prev) => {
      const oldIndex = prev.findIndex((status) => status.id === Number(active.id));
      const newIndex = prev.findIndex((status) => status.id === Number(over.id));
      if (oldIndex === -1 || newIndex === -1) {
        return prev;
      }
      const next = arrayMove(prev, oldIndex, newIndex);
      const payload = next.map((status, index) => ({ id: status.id, position: index }));
      reorderStatuses.mutate({ items: payload });
      return next.map((status, index) => ({ ...status, position: index }));
    });
  };

  const handleFieldChange = (
    statusId: number,
    field: "name" | "category" | "color" | "icon",
    value: string
  ) => {
    setDrafts((prev) => {
      const existing = prev[statusId];
      const baseName = existing?.name ?? "";
      const baseCategory = existing?.category ?? "todo";
      const baseColor = existing?.color ?? defaultsForCategory(baseCategory).color;
      const baseIcon = existing?.icon ?? defaultsForCategory(baseCategory).icon;

      if (field === "category") {
        const nextCategory = value as TaskStatusCategory;
        const swapped = maybeSwapDefaultsOnCategoryChange(
          baseCategory,
          nextCategory,
          baseColor,
          baseIcon
        );
        return {
          ...prev,
          [statusId]: {
            name: baseName,
            category: nextCategory,
            color: swapped.color,
            icon: swapped.icon,
          },
        };
      }

      return {
        ...prev,
        [statusId]: {
          name: field === "name" ? value : baseName,
          category: baseCategory,
          color: field === "color" ? value : baseColor,
          icon: field === "icon" ? (value as IconName) : baseIcon,
        },
      };
    });
  };

  const handleNewCategoryChange = (nextCategory: TaskStatusCategory) => {
    const swapped = maybeSwapDefaultsOnCategoryChange(newCategory, nextCategory, newColor, newIcon);
    setNewCategory(nextCategory);
    setNewColor(swapped.color);
    setNewIcon(swapped.icon);
  };

  const handleSaveAll = async () => {
    const updates: Array<{ statusId: number; data: Record<string, unknown>; statusName: string }> =
      [];

    orderedStatuses.forEach((status) => {
      const draft = drafts[status.id];
      if (!draft) {
        return;
      }
      const payload: Record<string, unknown> = {};
      const trimmedName = draft.name.trim();
      if (trimmedName && trimmedName !== status.name) {
        payload.name = trimmedName;
      }
      if (draft.category && draft.category !== status.category) {
        payload.category = draft.category;
      }
      if (draft.color && draft.color !== status.color) {
        payload.color = draft.color;
      }
      if (draft.icon && draft.icon !== status.icon) {
        payload.icon = draft.icon;
      }
      if (Object.keys(payload).length > 0) {
        updates.push({ statusId: status.id, data: payload, statusName: status.name });
      }
    });

    if (updates.length === 0) {
      toast.info(t("statuses.noChanges"));
      return;
    }

    // Execute all updates with individual error handling
    const results = await Promise.allSettled(
      updates.map(({ statusId, data }) =>
        bulkUpdateStatus.mutateAsync({
          statusId,
          data: data as {
            name?: string | null;
            category?: TaskStatusCategory | null;
            color?: string | null;
            icon?: string | null;
          },
        })
      )
    );

    const succeeded: string[] = [];
    const failed: Array<{ statusName: string; error: string }> = [];

    results.forEach((result, index) => {
      const update = updates[index];
      if (result.status === "fulfilled") {
        succeeded.push(update.statusName);
      } else {
        failed.push({
          statusName: update.statusName,
          error: getErrorMessage(result.reason, "projects:statuses.unknownError"),
        });
      }
    });

    if (succeeded.length > 0) {
      toast.success(t("statuses.bulkUpdated", { count: succeeded.length }));
    }

    if (failed.length > 0) {
      failed.forEach(({ statusName, error }) => {
        // ``error`` interpolated into the message — run it through the
        // shared resolver so a backend error code becomes a localized
        // string instead of "[object Object]" or a raw key.
        toast.error(
          t("statuses.bulkUpdateError", { name: statusName, error: getErrorMessage(error) })
        );
      });
    }

    // The centralized hook invalidates per-call, but we also need to ensure
    // all tasks are refreshed after bulk edits (category changes may affect task display).
    void invalidate(q.projectTaskStatuses(projectId), q.allTasks());
  };

  const hasChanges = useMemo(() => {
    return orderedStatuses.some((status) => {
      const draft = drafts[status.id];
      if (!draft) {
        return false;
      }
      const trimmedName = draft.name.trim();
      return (
        (trimmedName && trimmedName !== status.name) ||
        (draft.category && draft.category !== status.category) ||
        (draft.color && draft.color !== status.color) ||
        (draft.icon && draft.icon !== status.icon)
      );
    });
  }, [orderedStatuses, drafts]);

  const handleDefaultChange = (statusId: number) => {
    if (statusId === defaultStatusId) {
      return;
    }
    updateStatus.mutate({ statusId, data: { is_default: true } });
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
    ? orderedStatuses.filter((status) => status.id !== deleteTarget.id)
    : [];
  const isOnlyStatus = Boolean(deleteTarget) && fallbackOptions.length === 0;

  const isLoading = statusesQuery.isLoading || statusesQuery.isRefetching;
  const statuses = useMemo(() => {
    const source = orderedStatuses.length ? orderedStatuses : (statusesQuery.data ?? []);
    return sortStatuses(source);
  }, [orderedStatuses, statusesQuery.data]);

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t("statuses.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!canManage ? (
          <p className="text-muted-foreground text-sm">{t("statuses.noManagePermission")}</p>
        ) : null}
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
              <SelectContent>
                {categoryOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <IconPicker
              value={newIcon}
              onValueChange={(icon) => setNewIcon(icon)}
              triggerPlaceholder={t("statuses.iconPlaceholder")}
              disabled={!canManage || createStatus.isPending}
            />
            <ColorPickerPopover
              className="h-9 w-40"
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

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-sm">{t("statuses.existingStatuses")}</h4>
            <div className="flex items-center gap-2">
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : null}
              {canManage && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSaveAll}
                  disabled={!hasChanges || updateStatus.isPending}
                >
                  <Save className="h-4 w-4" />
                  {t("statuses.saveChanges")}
                </Button>
              )}
            </div>
          </div>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead className="min-w-40">{t("common:name")}</TableHead>
                  <TableHead>{t("statuses.categoryColumn")}</TableHead>
                  <TableHead className="w-32">{t("statuses.iconColumn")}</TableHead>
                  <TableHead className="w-40">{t("statuses.colorColumn")}</TableHead>
                  <TableHead className="w-24 text-center">{t("statuses.defaultColumn")}</TableHead>
                  <TableHead className="w-20 text-right">{t("common:actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                  <SortableContext
                    items={statuses.map((status) => status.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    {statuses.map((status) => (
                      <SortableStatusRow
                        key={status.id}
                        status={status}
                        draft={drafts[status.id]}
                        disabled={!canManage}
                        isDefault={status.id === defaultStatusId}
                        onFieldChange={handleFieldChange}
                        onSetDefault={handleDefaultChange}
                        onDelete={() => {
                          setDeleteTarget(status);
                          setFallbackId(FALLBACK_AUTO);
                        }}
                        t={t}
                        categoryOptions={categoryOptions}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
                {statuses.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="py-6 text-center text-muted-foreground text-sm"
                    >
                      {t("statuses.noStatuses")}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </div>
      </CardContent>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="bg-card">
          <DialogHeader>
            <DialogTitle>{t("statuses.deleteTitle")}</DialogTitle>
            <DialogDescription>
              {t("statuses.deleteDescription", { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          {isOnlyStatus ? (
            <p className="text-muted-foreground text-sm">{t("statuses.onlyStatus")}</p>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="fallback-status">{t("statuses.fallbackLabel")}</Label>
              <Select value={fallbackId} onValueChange={setFallbackId}>
                <SelectTrigger id="fallback-status">
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
            </div>
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
    </Card>
  );
};

interface SortableStatusRowProps {
  status: TaskStatusRead;
  draft?: { name: string; category: TaskStatusCategory; color: string; icon: IconName };
  disabled: boolean;
  isDefault: boolean;
  onFieldChange: (
    statusId: number,
    field: "name" | "category" | "color" | "icon",
    value: string
  ) => void;
  onSetDefault: (statusId: number) => void;
  onDelete: () => void;
  t: TFunction<"projects">;
  categoryOptions: { value: TaskStatusCategory; label: string }[];
}

const SortableStatusRow = ({
  status,
  draft,
  disabled,
  isDefault,
  onFieldChange,
  onSetDefault,
  onDelete,
  t,
  categoryOptions,
}: SortableStatusRowProps) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: status.id,
    disabled,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <TableRow ref={setNodeRef} style={style} className={cn(isDragging && "bg-muted/40")}>
      <TableCell>
        <button
          type="button"
          className="text-muted-foreground"
          {...attributes}
          {...listeners}
          disabled={disabled}
          aria-label={t("statuses.reorder")}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      </TableCell>
      <TableCell>
        <Input
          value={draft?.name ?? status.name}
          onChange={(event) => onFieldChange(status.id, "name", event.target.value)}
          disabled={disabled}
        />
      </TableCell>
      <TableCell>
        <Select
          value={draft?.category ?? status.category}
          onValueChange={(value) => onFieldChange(status.id, "category", value)}
          disabled={disabled}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {categoryOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
      <TableCell>
        <IconPicker
          value={(draft?.icon ?? status.icon) as IconName}
          onValueChange={(icon) => onFieldChange(status.id, "icon", icon)}
          triggerPlaceholder={t("statuses.iconPlaceholder")}
          disabled={disabled}
        />
      </TableCell>
      <TableCell>
        <ColorPickerPopover
          className="h-9"
          value={draft?.color ?? status.color}
          onChangeComplete={(hex) => onFieldChange(status.id, "color", hex)}
          disabled={disabled}
          triggerLabel={t("statuses.colorPlaceholder")}
        />
      </TableCell>
      <TableCell className="text-center">
        <Checkbox
          checked={isDefault}
          onCheckedChange={(checked) => {
            if (checked) {
              onSetDefault(status.id);
            }
          }}
          aria-label={t("statuses.setAsDefault")}
          disabled={disabled || isDefault}
        />
      </TableCell>
      <TableCell className="text-right">
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
          disabled={disabled}
          aria-label={t("statuses.deleteStatus", { name: status.name })}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </TableCell>
    </TableRow>
  );
};
