import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateToolDialog } from "@/components/initiativeTools/shared/CreateToolDialog";
import { ProjectDateFields } from "@/components/projects/ProjectDateFields";
import { useTemplateProjects } from "@/hooks/useProjects";
import { dateRangeBounds } from "@/lib/dateRange";
import type { DialogProps } from "@/types/dialog";
import { EmojiField } from "@/ui/emoji-picker";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

const NO_TEMPLATE_VALUE = "template-none";

type CreateProjectDialogProps = DialogProps & {
  initiativeId: number;
  onSuccess: (project: { id: number }) => void;
};

/**
 * The shared create dialog with what a project asks for beside it: an icon,
 * its dates, and a template to start from, or whether it is one.
 */
export const CreateProjectDialog = ({
  open,
  onOpenChange,
  initiativeId,
  onSuccess,
}: CreateProjectDialogProps) => {
  const { t } = useTranslation("projects");
  const [icon, setIcon] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState(NO_TEMPLATE_VALUE);
  const [isTemplateProject, setIsTemplateProject] = useState(false);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (!open) {
      setIcon("");
      setStartDate("");
      setEndDate("");
      setSelectedTemplateId(NO_TEMPLATE_VALUE);
      setIsTemplateProject(false);
    }
  }

  const templatesQuery = useTemplateProjects(open);
  // A template is started from only while the new project is not one itself.
  const template = isTemplateProject
    ? undefined
    : templatesQuery.data?.items?.find((item) => String(item.id) === selectedTemplateId);

  const { isInverted: datesInverted } = dateRangeBounds(startDate, endDate);

  return (
    <CreateToolDialog
      open={open}
      onOpenChange={onOpenChange}
      tool={Tool.project}
      text={{
        ns: "projects",
        create: "createDialog.createProject",
        createDescription: "createDialog.description",
      }}
      initiativeId={initiativeId}
      onSuccess={onSuccess}
      extra={{
        payload: {
          is_template: isTemplateProject,
          ...(icon.trim() ? { icon: icon.trim() } : {}),
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate ? { end_date: endDate } : {}),
          ...(template ? { template_id: template.id } : {}),
        },
        // Picking a template starts the description from the template's own.
        description: template
          ? { from: String(template.id), text: template.description ?? "" }
          : undefined,
        invalid: datesInverted,
        field: (
          <>
            <Field label={t("createDialog.iconLabel")}>
              <EmojiField value={icon || undefined} onChange={(emoji) => setIcon(emoji ?? "")} />
            </Field>
            <ProjectDateFields
              idPrefix="create-project"
              startDate={startDate}
              endDate={endDate}
              onStartDateChange={setStartDate}
              onEndDateChange={setEndDate}
            />
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
                    {templatesQuery.data?.items?.map((item) => (
                      <SelectItem key={item.id} value={String(item.id)}>
                        {item.name}
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
                  setIsTemplateProject(checked);
                  if (checked) setSelectedTemplateId(NO_TEMPLATE_VALUE);
                }}
              />
            </div>
          </>
        ),
      }}
    />
  );
};
