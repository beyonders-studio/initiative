/**
 * Adding a task type: one of the ready-made ones, grouped by what they are
 * for, a blank one, or a copy of one the project already has. A ready-made
 * one brings its look, what a new task of it starts with, and its fields.
 */

import { Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskTypeCreate, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { ReadyMadeGallery } from "@/components/shared/ReadyMadeGallery";
import { TaskTypeIcon, TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTaskTypeGallery } from "@/hooks/useProjects";
import { listFormat } from "@/lib/intl";

/** Where a new type starts: nothing, a ready-made one, or one of the project's. */
type Start = { kind: "blank" } | { kind: "gallery"; key: string } | { kind: "type"; id: number };

interface TaskTypeAddDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  types: TaskTypeRead[];
  saving: boolean;
  onAdd: (data: TaskTypeCreate) => void;
}

export const TaskTypeAddDialog = ({
  open,
  onOpenChange,
  projectId,
  types,
  saving,
  onAdd,
}: TaskTypeAddDialogProps) => {
  const { t, i18n } = useTranslation(["projects", "common", "errors"]);
  const gallery = useTaskTypeGallery(projectId, { enabled: open });
  const [start, setStart] = useState<Start>({ kind: "blank" });
  const [name, setName] = useState("");

  // Opened afresh each time.
  useEffect(() => {
    if (open) {
      setStart({ kind: "blank" });
      setName("");
    }
  }, [open]);

  // Names are unique within a project, whatever their case; the server says
  // so too, but the dialog can say it before the reader presses Add.
  const trimmed = name.trim();
  const has = (candidate: string) =>
    types.some((type) => type.name.toLocaleLowerCase() === candidate.toLocaleLowerCase());
  const nameTaken = has(trimmed);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed || nameTaken) return;
    onAdd({
      name: trimmed,
      ...(start.kind === "gallery" ? { gallery_key: start.key } : {}),
      // The new type takes the look and page of the one it starts from.
      ...(start.kind === "type" ? { start_from_type_id: start.id } : {}),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90dvh] flex-col bg-card">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("taskTypes.addTitle")}</DialogTitle>
            <DialogDescription>{t("taskTypes.addDescription")}</DialogDescription>
          </DialogHeader>

          {/* Positioned, so the hidden inputs Radix adds to form controls
              scroll with the list instead of stretching the dialog. */}
          <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <ReadyMadeGallery
              blank={{
                name: t("taskTypes.gallery.blank"),
                hint: t("taskTypes.gallery.blankHint"),
              }}
              loading={gallery.isLoading}
              groups={(gallery.data ?? []).map((group) => ({
                key: group.key,
                name: group.name,
                entries: group.entries.map((entry) => ({
                  key: entry.key,
                  name: entry.name,
                  hint: entry.hint,
                  icon: <TaskTypeIcon type={entry} className="mt-0.5 h-4 w-4" />,
                  note: has(entry.name) ? t("taskTypes.gallery.alreadyHere") : undefined,
                  brings:
                    entry.fields.length > 0
                      ? t("taskTypes.gallery.adds", {
                          fields: listFormat(i18n.language, { type: "conjunction" }).format(
                            entry.fields.map((field) => field.name)
                          ),
                        })
                      : undefined,
                })),
              }))}
              chosen={
                start.kind === "blank" ? null : start.kind === "gallery" ? start.key : undefined
              }
              onChoose={(entry) => {
                if (!entry) {
                  setStart({ kind: "blank" });
                  return;
                }
                setStart({ kind: "gallery", key: entry.key });
                setName(entry.name);
              }}
            />

            <div className="space-y-2">
              <Label htmlFor="new-task-type-start-from">{t("taskTypes.startFromLabel")}</Label>
              <Select
                value={start.kind === "type" ? String(start.id) : ""}
                onValueChange={(value) => setStart({ kind: "type", id: Number(value) })}
              >
                <SelectTrigger id="new-task-type-start-from">
                  <SelectValue placeholder={t("taskTypes.startFromPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {types.map((type) => (
                    <SelectItem key={type.id} value={String(type.id)}>
                      <TaskTypeOption type={type} />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("taskTypes.startFromHint")}</p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-task-type-name">{t("taskTypes.nameLabel")}</Label>
            <Input
              id="new-task-type-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("taskTypes.namePlaceholder")}
              maxLength={100}
              aria-invalid={nameTaken || undefined}
              aria-describedby={nameTaken ? "new-task-type-name-error" : undefined}
            />
            {nameTaken ? (
              <p id="new-task-type-name-error" className="text-destructive text-sm">
                {t("errors:TASK_TYPE_NAME_TAKEN")}
              </p>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={!trimmed || nameTaken || saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("taskTypes.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
