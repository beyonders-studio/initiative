/**
 * Adding a task type: one of the ready-made ones, grouped by what they are
 * for, a blank one, or a copy of one the project already has. A ready-made
 * one brings its look, what a new task of it starts with, and its fields.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TaskTypeCreate, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { ReadyMadeGallery } from "@/components/shared/ReadyMadeGallery";
import { TaskTypeIcon, TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { useTaskTypeGallery } from "@/hooks/useProjects";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { listFormat } from "@/ui/lib/intl";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

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

export const TaskTypeAddDialog = ({ open, onOpenChange, ...props }: TaskTypeAddDialogProps) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent>
      <TaskTypeAddForm {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts afresh.
const TaskTypeAddForm = ({
  projectId,
  types,
  saving,
  onAdd,
}: Omit<TaskTypeAddDialogProps, "open" | "onOpenChange">) => {
  const { t, i18n } = useTranslation(["projects", "common", "errors"]);
  const gallery = useTaskTypeGallery(projectId);
  const [start, setStart] = useState<Start>({ kind: "blank" });
  const [name, setName] = useState("");

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
    <form onSubmit={handleSubmit} className="contents">
      <DialogHeader>
        <DialogTitle>{t("taskTypes.addTitle")}</DialogTitle>
        <DialogDescription>{t("taskTypes.addDescription")}</DialogDescription>
      </DialogHeader>

      <DialogBody className="space-y-4">
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
          chosen={start.kind === "blank" ? null : start.kind === "gallery" ? start.key : undefined}
          onChoose={(entry) => {
            if (!entry) {
              setStart({ kind: "blank" });
              return;
            }
            setStart({ kind: "gallery", key: entry.key });
            setName(entry.name);
          }}
        />

        <Field label={t("taskTypes.startFromLabel")} hint={t("taskTypes.startFromHint")}>
          <Select
            value={start.kind === "type" ? String(start.id) : ""}
            onValueChange={(value) => setStart({ kind: "type", id: Number(value) })}
          >
            <SelectTrigger>
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
        </Field>
      </DialogBody>

      <Field label={t("taskTypes.nameLabel")} error={nameTaken && t("errors:TASK_TYPE_NAME_TAKEN")}>
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("taskTypes.namePlaceholder")}
          maxLength={100}
        />
      </Field>

      <DialogFooter
        submitLabel={t("taskTypes.add")}
        pending={saving}
        disabled={!trimmed || nameTaken}
      />
    </form>
  );
};
