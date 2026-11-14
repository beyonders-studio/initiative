/**
 * The table a project's task statuses and task types are managed in: a row
 * each, in their order, dragged by the handle to reorder. A row's name, icon
 * and colour are edited in place and saved together; one row is the default.
 */

import { DndContext, type DragEndEvent } from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2, Save, Trash2 } from "lucide-react";
import type { IconName } from "lucide-react/dynamic";
import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";
import { Checkbox } from "@/ui/checkbox";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { IconPicker } from "@/ui/icon-picker";
import { Input } from "@/ui/input";
import { useDragSensors } from "@/ui/lib/useDragSensors";
import { cn } from "@/ui/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

interface Definition {
  id: number;
  name: string;
  color: string;
  icon: string;
  position: number;
  is_default: boolean;
}

/** A row's fields the reader has changed and not saved, by name. */
type Draft = Record<string, string>;

/** Rows in their order: by position, then by id. */
export const byPosition = <T extends { id: number; position: number }>(rows: T[]): T[] =>
  [...rows].sort((a, b) => a.position - b.position || a.id - b.id);

/** The fields of a draft that differ from its row. */
const differing = <T extends Definition>(row: T, draft: Draft = {}): Draft =>
  Object.fromEntries(
    Object.entries(draft).filter(([field, value]) => value !== row[field as keyof T])
  );

interface DefinitionTableProps<T extends Definition> {
  /** The group of `projects` keys the table's words come from. */
  keys: "statuses" | "taskTypes";
  /** The rows as read, undefined until they are. */
  rows: T[] | undefined;
  loading: boolean;
  canManage: boolean;
  /** Saves a new order, answering with the rows in it. */
  reorder: {
    mutateAsync: (request: { items: { id: number; position: number }[] }) => Promise<T[]>;
    isPending: boolean;
  };
  /** Saves a row's changed fields, or makes it the default. */
  onUpdate: (id: number, data: Draft | { is_default: true }) => Promise<unknown>;
  /** A change is being saved. */
  saving: boolean;
  onDelete: (row: T) => void;
  /** A column of the caller's own after the name: its heading, and its cell
   *  for a row as drafted, with the way to change that draft. */
  column?: { head: string; cell: (row: T, edit: (changes: Draft) => void) => ReactNode };
  /** Buttons before a row's delete. */
  rowActions?: (row: T) => ReactNode;
  /** Buttons after Save changes. */
  toolbar?: ReactNode;
  /** Text under the table. */
  notes?: ReactNode;
  /** What the card shows above the table. */
  children?: ReactNode;
}

export const DefinitionTable = <T extends Definition>({
  keys,
  rows,
  loading,
  canManage,
  reorder,
  onUpdate,
  saving,
  onDelete,
  column,
  rowActions,
  toolbar,
  notes,
  children,
}: DefinitionTableProps<T>) => {
  const sensors = useDragSensors();
  const { t } = useTranslation(["projects", "common"]);
  const [ordered, setOrdered] = useState<T[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});

  // A refresh takes the rows anew and keeps what the reader has changed from
  // them; while a reorder is saving, the order it moved to stays.
  useEffect(() => {
    if (!rows || reorder.isPending) {
      return;
    }
    setOrdered(byPosition(rows));
    setDrafts((prev) =>
      Object.fromEntries(rows.map((row) => [row.id, differing(row, prev[row.id])]))
    );
  }, [rows, reorder.isPending]);

  const list = ordered.length > 0 ? ordered : byPosition(rows ?? []);
  const defaultId = (list.find((row) => row.is_default) ?? list[0])?.id;

  /** Each row's unsaved changes: the fields that differ, the name trimmed,
   *  none left empty. */
  const updates = list.flatMap((row) => {
    const changes = Object.entries(drafts[row.id] ?? {}).flatMap(([field, value]) => {
      const next = field === "name" ? value.trim() : value;
      return next && next !== row[field as keyof T] ? [[field, next] as const] : [];
    });
    return changes.length > 0 ? [{ row, changes: Object.fromEntries(changes) }] : [];
  });

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    const from = list.findIndex((row) => row.id === active.id);
    const to = list.findIndex((row) => row.id === over?.id);
    if (!canManage || from === -1 || to === -1 || from === to) {
      return;
    }
    const next = arrayMove(list, from, to).map((row, position) => ({ ...row, position }));
    setOrdered(next);
    void reorder.mutateAsync({ items: next.map(({ id, position }) => ({ id, position })) }).then(
      (saved) => {
        setOrdered(byPosition(saved));
        toast.success(t(`${keys}.orderSaved`));
      },
      (error) => toast.error(getErrorMessage(error, `projects:${keys}.reorderError`))
    );
  };

  const makeDefault = (row: T) =>
    onUpdate(row.id, { is_default: true }).then(
      () => toast.success(t(`${keys}.updated`)),
      (error) => toast.error(getErrorMessage(error, `projects:${keys}.updateError`))
    );

  const saveAll = async () => {
    if (updates.length === 0) {
      toast.info(t(`${keys}.noChanges`));
      return;
    }
    const results = await Promise.allSettled(
      updates.map(({ row, changes }) => onUpdate(row.id, changes))
    );
    let saved = 0;
    results.forEach((result, index) => {
      if (result.status === "fulfilled") {
        saved += 1;
        return;
      }
      toast.error(
        t(`${keys}.bulkUpdateError`, {
          name: updates[index].row.name,
          error: getErrorMessage(result.reason, `projects:${keys}.updateError`),
        })
      );
    });
    if (saved > 0) {
      toast.success(t(`${keys}.bulkUpdated`, { count: saved }));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardDescription>{t(`${keys}.description`)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!canManage ? (
          <p className="text-muted-foreground text-sm">{t(`${keys}.noManagePermission`)}</p>
        ) : null}
        {children}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-semibold text-sm">{t(`${keys}.existing`)}</h4>
            <div className="flex items-center gap-2">
              {loading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
              {canManage ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={saveAll}
                    disabled={updates.length === 0 || saving}
                  >
                    <Save className="h-4 w-4" />
                    {t(`${keys}.saveChanges`)}
                  </Button>
                  {toolbar}
                </>
              ) : null}
            </div>
          </div>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10" />
                  <TableHead className="min-w-40">{t("common:name")}</TableHead>
                  {column ? <TableHead>{column.head}</TableHead> : null}
                  <TableHead className="w-32">{t(`${keys}.iconColumn`)}</TableHead>
                  <TableHead className="w-40">{t(`${keys}.colorColumn`)}</TableHead>
                  <TableHead className="w-24 text-center">{t(`${keys}.defaultColumn`)}</TableHead>
                  <TableHead className="text-right">{t("common:actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                  <SortableContext
                    items={list.map((row) => row.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    {list.map((row) => {
                      const draft = drafts[row.id] ?? {};
                      const edit = (changes: Draft) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [row.id]: differing(row, { ...prev[row.id], ...changes }),
                        }));
                      const isDefault = row.id === defaultId;
                      return (
                        <SortableRow
                          key={row.id}
                          id={row.id}
                          disabled={!canManage}
                          label={t(`${keys}.reorder`)}
                        >
                          <TableCell>
                            <Input
                              value={draft.name ?? row.name}
                              onChange={(event) => edit({ name: event.target.value })}
                              disabled={!canManage}
                              maxLength={100}
                              aria-label={t("common:name")}
                            />
                          </TableCell>
                          {column ? (
                            <TableCell>{column.cell({ ...row, ...draft }, edit)}</TableCell>
                          ) : null}
                          <TableCell>
                            <IconPicker
                              value={(draft.icon ?? row.icon) as IconName}
                              onValueChange={(icon) => edit({ icon })}
                              triggerPlaceholder={t(`${keys}.iconPlaceholder`)}
                              disabled={!canManage}
                            />
                          </TableCell>
                          <TableCell>
                            <ColorPickerPopover
                              value={draft.color ?? row.color}
                              onChangeComplete={(color) => edit({ color })}
                              disabled={!canManage}
                              triggerLabel={t(`${keys}.colorPlaceholder`)}
                            />
                          </TableCell>
                          <TableCell className="text-center">
                            <Checkbox
                              checked={isDefault}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  void makeDefault(row);
                                }
                              }}
                              aria-label={t(`${keys}.makeDefault`, { name: row.name })}
                              disabled={!canManage || isDefault}
                            />
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center justify-end gap-1">
                              {rowActions?.(row)}
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-destructive hover:text-destructive"
                                onClick={() => onDelete(row)}
                                disabled={!canManage}
                                aria-label={t(`${keys}.deleteNamed`, { name: row.name })}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </SortableRow>
                      );
                    })}
                  </SortableContext>
                </DndContext>
                {list.length === 0 && !loading ? (
                  <TableRow>
                    <TableCell
                      colSpan={column ? 7 : 6}
                      className="py-6 text-center text-muted-foreground text-sm"
                    >
                      {t(`${keys}.empty`)}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          {notes}
        </div>
      </CardContent>
    </Card>
  );
};

/** A row dragged by the handle in its first cell. */
const SortableRow = ({
  id,
  disabled,
  label,
  children,
}: {
  id: number;
  disabled: boolean;
  /** The handle's label. */
  label: string;
  children: ReactNode;
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled,
  });

  return (
    <TableRow
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(isDragging && "bg-muted/40")}
    >
      <TableCell>
        <button
          type="button"
          className="text-muted-foreground"
          {...attributes}
          {...listeners}
          disabled={disabled}
          aria-label={label}
        >
          <GripVertical className="h-4 w-4" />
        </button>
      </TableCell>
      {children}
    </TableRow>
  );
};
