import { AlertTriangle } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { Combobox } from "@/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/ui/dialog";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

type MoveTaskDialogProps = {
  trigger?: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: ProjectRead[];
  currentProjectId?: number | null;
  isLoading?: boolean;
  isSaving?: boolean;
  hasError?: boolean;
  onConfirm: (targetProjectId: number) => void;
};

export const MoveTaskDialog = ({
  trigger,
  open,
  onOpenChange,
  projects,
  currentProjectId = null,
  isLoading = false,
  isSaving = false,
  hasError = false,
  onConfirm,
}: MoveTaskDialogProps) => {
  const { t } = useTranslation(["tasks", "common"]);
  const availableProjects = useMemo(() => {
    return projects.filter((project) => project.id !== currentProjectId);
  }, [projects, currentProjectId]);
  const [selectedValue, setSelectedValue] = useState<string>("");

  useEffect(() => {
    if (!open) {
      setSelectedValue("");
      return;
    }
    if (selectedValue) {
      const stillValid = availableProjects.some((project) => String(project.id) === selectedValue);
      if (stillValid) {
        return;
      }
    }
    const fallback = availableProjects[0];
    setSelectedValue(fallback ? String(fallback.id) : "");
  }, [open, availableProjects, selectedValue]);

  const isDisabled = isLoading || availableProjects.length === 0 || hasError;

  const handleConfirm = () => {
    const parsed = Number(selectedValue);
    if (!Number.isFinite(parsed)) {
      return;
    }
    onConfirm(parsed);
  };

  const comboboxItems = useMemo(
    () =>
      availableProjects.map((project) => ({
        value: String(project.id),
        label: project.icon ? `${project.icon} ${project.name}` : project.name,
      })),
    [availableProjects]
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {trigger ? <DialogTrigger asChild>{trigger}</DialogTrigger> : null}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("move.title")}</DialogTitle>
          <DialogDescription>{t("move.description")}</DialogDescription>
        </DialogHeader>

        {hasError ? (
          <StatusMessage />
        ) : isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={3} avatar={false} />
          </SkeletonRegion>
        ) : availableProjects.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("move.noProjects")}</p>
        ) : (
          <Combobox
            items={comboboxItems}
            value={selectedValue}
            onValueChange={setSelectedValue}
            placeholder={t("move.searchPlaceholder")}
            disabled={isDisabled}
          />
        )}

        <div className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t("move.statusResetWarning")}</span>
        </div>

        <DialogFooter
          submitLabel={t("move.moveTask")}
          onSubmit={handleConfirm}
          pending={isSaving}
          pendingLabel={t("move.moving")}
          disabled={isDisabled || !selectedValue}
        />
      </DialogContent>
    </Dialog>
  );
};
