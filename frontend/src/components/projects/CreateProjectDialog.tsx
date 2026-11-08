import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectCreate, ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { CreateAccessSection } from "@/components/access/CreateAccessSection";
import { DEFAULT_GRANTS } from "@/components/access/grants";
import { ProjectDateFields } from "@/components/projects/ProjectDateFields";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCreateProject, useTemplateProjects } from "@/hooks/useProjects";
import { dateRangeBounds } from "@/lib/dateRange";
import type { DialogProps } from "@/types/dialog";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { EmojiField } from "@/ui/emoji-picker";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

const NO_TEMPLATE_VALUE = "template-none";

type CreateProjectDialogProps = DialogProps & {
  initiativeId: number;
  onSuccess: (project: { id: number }) => void;
};

export const CreateProjectDialog = ({
  open,
  onOpenChange,
  initiativeId,
  onSuccess,
}: CreateProjectDialogProps) => {
  const { t } = useTranslation(["projects", "common"]);
  // The initiative page's own cached read, for the dialog's label.
  const initiativeName = useInitiative(initiativeId).data?.name ?? null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(NO_TEMPLATE_VALUE);
  const [isTemplateProject, setIsTemplateProject] = useState(false);
  const [grants, setGrants] = useState<ResourceGrantSchema[]>([...DEFAULT_GRANTS]);

  const templatesQuery = useTemplateProjects(open);

  // Sync description from selected template
  useEffect(() => {
    if (isTemplateProject) {
      return;
    }
    if (selectedTemplateId === NO_TEMPLATE_VALUE) {
      return;
    }
    const templateId = Number(selectedTemplateId);
    if (!Number.isFinite(templateId)) {
      return;
    }
    const template = templatesQuery.data?.items?.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setDescription(template.description ?? "");
  }, [selectedTemplateId, templatesQuery.data, isTemplateProject]);

  const { isInverted: datesInverted } = dateRangeBounds(startDate, endDate);

  const createProjectMutation = useCreateProject();
  const createProject = {
    ...createProjectMutation,
    mutate: () => {
      if (datesInverted) {
        return;
      }
      const payload: ProjectCreate = {
        name,
        description,
        initiative_id: initiativeId,
        is_template: isTemplateProject,
        grants,
      };
      const trimmedIcon = icon.trim();
      if (trimmedIcon) {
        payload.icon = trimmedIcon;
      }
      if (startDate) {
        payload.start_date = startDate;
      }
      if (endDate) {
        payload.end_date = endDate;
      }
      if (!isTemplateProject && selectedTemplateId !== NO_TEMPLATE_VALUE) {
        payload.template_id = Number(selectedTemplateId);
      }
      createProjectMutation.mutate(payload, {
        onSuccess: (project) => {
          setName("");
          setDescription("");
          setIcon("");
          setStartDate("");
          setEndDate("");
          setSelectedTemplateId(NO_TEMPLATE_VALUE);
          setIsTemplateProject(false);
          setGrants([...DEFAULT_GRANTS]);
          onOpenChange(false);
          onSuccess(project);
        },
      });
    },
    isPending: createProjectMutation.isPending,
    isError: createProjectMutation.isError,
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createProject.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card">
        <DialogHeader>
          <DialogTitle>{t("createDialog.title")}</DialogTitle>
          <DialogDescription>{t("createDialog.description")}</DialogDescription>
        </DialogHeader>
        <form className="w-full max-w-lg" onSubmit={handleSubmit}>
          <div className="space-y-4">
            <Field label={t("createDialog.iconLabel")}>
              <EmojiField value={icon || undefined} onChange={(emoji) => setIcon(emoji ?? "")} />
            </Field>
            <Field label={t("common:name")}>
              <Input
                placeholder={t("createDialog.namePlaceholder")}
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </Field>
            <Field label={t("createDialog.descriptionLabel")}>
              <Textarea
                placeholder={t("createDialog.descriptionPlaceholder")}
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
            <ProjectDateFields
              idPrefix="create-project"
              startDate={startDate}
              endDate={endDate}
              onStartDateChange={setStartDate}
              onEndDateChange={setEndDate}
            />
            <div className="space-y-2">
              <Label>{t("createDialog.initiativeLabel")}</Label>
              <div className="rounded-md border px-3 py-2 text-sm">
                {initiativeName ?? t("filters.selectedInitiative")}
              </div>
            </div>
            <Field
              label={t("createDialog.templateLabel")}
              hint={isTemplateProject && t("createDialog.disableTemplateHint")}
            >
              {templatesQuery.isLoading ? (
                <p className="text-muted-foreground text-sm">
                  {t("createDialog.loadingTemplates")}
                </p>
              ) : templatesQuery.isError ? (
                <p className="text-destructive text-sm">{t("createDialog.templateLoadError")}</p>
              ) : (
                <Select
                  value={selectedTemplateId}
                  onValueChange={setSelectedTemplateId}
                  disabled={isTemplateProject}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("createDialog.noTemplate")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_TEMPLATE_VALUE}>
                      {t("createDialog.noTemplate")}
                    </SelectItem>
                    {templatesQuery.data?.items?.map((template) => (
                      <SelectItem key={template.id} value={String(template.id)}>
                        {template.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
            <div className="flex items-center justify-between rounded-lg border bg-muted/20 p-3">
              <div>
                <Label htmlFor="create-as-template" className="text-base">
                  {t("createDialog.saveAsTemplate")}
                </Label>
                <p className="text-muted-foreground text-xs">
                  {t("createDialog.saveAsTemplateHint")}
                </p>
              </div>
              <Switch
                id="create-as-template"
                checked={isTemplateProject}
                onCheckedChange={(checked) => {
                  const nextStatus = Boolean(checked);
                  setIsTemplateProject(nextStatus);
                  if (nextStatus) {
                    setSelectedTemplateId(NO_TEMPLATE_VALUE);
                  }
                }}
              />
            </div>
            <CreateAccessSection initiativeId={initiativeId} grants={grants} onChange={setGrants} />
            <div className="flex flex-wrap items-center gap-2">
              {createProject.isError ? (
                <p className="text-destructive text-sm">{t("createDialog.createError")}</p>
              ) : null}
              <div className="ml-auto flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={createProject.isPending}
                  onClick={() => onOpenChange(false)}
                >
                  {t("common:cancel")}
                </Button>
                <Button type="submit" disabled={createProject.isPending || datesInverted}>
                  {createProject.isPending
                    ? t("createDialog.creating")
                    : t("createDialog.createProject")}
                </Button>
              </div>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
};
