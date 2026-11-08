import { ListTodo } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead, TaskRead } from "@/api/generated/initiativeAPI.schemas";
import { ProjectPickerStep } from "@/components/tasks/ProjectPickerStep";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateTask } from "@/hooks/useTasks";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";

type ContactNewTaskDialogProps = DialogProps & {
  /** The contact the task is for: its name, and the initiative it goes in. */
  contact: { name: string; initiative_id: number };
  /** The task, once added: the caller links it. */
  onCreated: (task: TaskRead) => void;
};

/**
 * A task for a contact: its title, and the project in the contact's
 * initiative it goes in. Linking it to the contact is the caller's.
 */
export const ContactNewTaskDialog = ({
  open,
  onOpenChange,
  contact,
  onCreated,
}: ContactNewTaskDialogProps) => {
  const { t } = useTranslation(["contacts", "common"]);
  const id = useId();
  const communityId = useActiveCommunityId();
  const [title, setTitle] = useState("");
  const [project, setProject] = useState<ProjectRead | null>(null);

  const titleRef = useRef<HTMLInputElement>(null);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setTitle("");
      setProject(null);
    }
  }

  // The project comes first, as it does everywhere a task is added; once it is
  // picked, the title is what is asked for next.
  useEffect(() => {
    if (project) titleRef.current?.focus();
  }, [project]);

  const create = useCreateTask({
    onSuccess: (task) => {
      onOpenChange(false);
      onCreated(task);
    },
  });
  const canSubmit = title.trim() !== "" && project !== null && !create.isPending;
  const submit = () => {
    if (!canSubmit || !project) return;
    create.mutate({ project_id: project.id, title: title.trim() });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto bg-card sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("newTask")}</DialogTitle>
          <DialogDescription>{t("task.description", { name: contact.name })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{t("task.project")}</Label>
            {project ? (
              <div className="flex items-center gap-3 rounded-lg border p-3">
                <ListTodo className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate font-medium text-sm">{project.name}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => setProject(null)}>
                  {t("task.change")}
                </Button>
              </div>
            ) : (
              <ProjectPickerStep
                communityId={communityId}
                initiativeId={contact.initiative_id}
                onPick={setProject}
              />
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-title`}>{t("task.title")}</Label>
            <Input
              ref={titleRef}
              id={`${id}-title`}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submit();
                }
              }}
              placeholder={t("task.titlePlaceholder")}
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" onClick={submit} pending={create.isPending} disabled={!canSubmit}>
            {t("task.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
