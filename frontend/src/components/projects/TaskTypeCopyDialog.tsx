/**
 * Copying task types from another project: each with its look, its page and
 * what a new task of it starts with. One whose name this project has already
 * stays where it is, and no more come than the project has room for.
 */

import { Loader2 } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type TaskTypeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { TaskTypeOption } from "@/components/tasks/TaskTypeOption";
import { useProjects, useProjectTaskTypes } from "@/hooks/useProjects";
import { toolViewParams } from "@/lib/tools";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

interface TaskTypeCopyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  types: TaskTypeRead[];
  /** How many more types the project has room for. */
  room: number;
  saving: boolean;
  onCopy: (sourceProjectId: number, typeIds: number[]) => void;
}

export const TaskTypeCopyDialog = ({
  open,
  onOpenChange,
  projectId,
  types,
  room,
  saving,
  onCopy,
}: TaskTypeCopyDialogProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const projects = useProjects(
    { slim: true, ...toolViewParams(Tool.project, "active") },
    { enabled: open }
  );
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const sourceTypes = useProjectTaskTypes(sourceId, { enabled: open && sourceId !== null });

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setSourceId(null);
      setChosen(new Set());
    }
  }

  const others = (projects.data?.items ?? []).filter((project) => project.id !== projectId);
  const here = useMemo(() => new Set(types.map((type) => type.name.toLocaleLowerCase())), [types]);
  const isHere = (type: TaskTypeRead) => here.has(type.name.toLocaleLowerCase());

  const pickSource = (value: string) => {
    const id = Number(value);
    setSourceId(id);
    setChosen(new Set());
  };

  // Every type that can come is chosen once its project is, while there is
  // room for it.
  useEffect(() => {
    if (!sourceTypes.data) return;
    const coming = sourceTypes.data.filter((type) => !here.has(type.name.toLocaleLowerCase()));
    setChosen(new Set(coming.slice(0, room).map((type) => type.id)));
  }, [sourceTypes.data, here, room]);

  const toggle = (typeId: number, on: boolean) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (on) next.add(typeId);
      else next.delete(typeId);
      return next;
    });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (sourceId === null || chosen.size === 0) return;
    const order = (sourceTypes.data ?? []).map((type) => type.id);
    onCopy(
      sourceId,
      order.filter((id) => chosen.has(id))
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90dvh] flex-col bg-card">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("taskTypes.copy.title")}</DialogTitle>
            <DialogDescription>{t("taskTypes.copy.description")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="copy-types-from">{t("taskTypes.copy.fromLabel")}</Label>
            <Select value={sourceId === null ? "" : String(sourceId)} onValueChange={pickSource}>
              <SelectTrigger id="copy-types-from">
                <SelectValue placeholder={t("taskTypes.copy.fromPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {others.map((project) => (
                  <SelectItem key={project.id} value={String(project.id)}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Positioned, so the hidden inputs Radix adds to form controls
              scroll with the list instead of stretching the dialog. */}
          {sourceId !== null ? (
            <fieldset className="relative min-h-0 flex-1 space-y-2 overflow-y-auto">
              <legend className="font-medium text-sm">{t("taskTypes.copy.typesLabel")}</legend>
              {sourceTypes.isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : null}
              {(sourceTypes.data ?? []).map((type) => {
                const already = isHere(type);
                const checked = chosen.has(type.id);
                const full = !checked && chosen.size >= room;
                const id = `copy-type-${type.id}`;
                return (
                  <div key={type.id} className="flex items-center gap-2">
                    <Checkbox
                      id={id}
                      checked={checked}
                      disabled={already || full}
                      onCheckedChange={(value) => toggle(type.id, value === true)}
                    />
                    <Label htmlFor={id} className="flex items-center gap-2 font-normal">
                      <TaskTypeOption type={type} />
                      {already ? (
                        <span className="text-muted-foreground text-xs">
                          {t("taskTypes.copy.alreadyHere")}
                        </span>
                      ) : null}
                    </Label>
                  </div>
                );
              })}
              {room === 0 ? (
                <p className="text-muted-foreground text-sm">{t("taskTypes.copy.noRoom")}</p>
              ) : null}
            </fieldset>
          ) : null}

          <DialogFooter
            submitLabel={t("taskTypes.copy.submit", { count: chosen.size })}
            pending={saving}
            disabled={sourceId === null || chosen.size === 0}
          />
        </form>
      </DialogContent>
    </Dialog>
  );
};
