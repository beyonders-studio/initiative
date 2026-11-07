/**
 * Whether this is a template: one meant to be copied rather than worked in,
 * listed with its initiative's templates.
 *
 * One card for every tool that has templates (projects and files). A tool
 * opts in by handing its settings the `template` mutation; without one there
 * is no card.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

export const ToolTemplateCard = () => {
  const { t } = useTranslation("common");
  const { entity, template } = useToolSettings();
  const [isTemplate, setIsTemplate] = useState(Boolean(entity.is_template));

  const [prevIsTemplate, setPrevIsTemplate] = useState(entity.is_template);
  if (prevIsTemplate !== entity.is_template) {
    setPrevIsTemplate(entity.is_template);
    setIsTemplate(Boolean(entity.is_template));
  }

  if (!template) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <div>
          <CardTitle>{t("toolSettings.template.title")}</CardTitle>
          <CardDescription>{t("toolSettings.template.description")}</CardDescription>
        </div>
        <Switch
          id="tool-settings-template"
          checked={isTemplate}
          onCheckedChange={(value) => {
            // Saved on flip, like the comment switch: the switch shows the new
            // state at once and puts the old one back if the write fails.
            const previous = isTemplate;
            setIsTemplate(value);
            template.mutate({ is_template: value }, { onError: () => setIsTemplate(previous) });
          }}
          disabled={!entity.can.edit || template.isPending}
          aria-label={t("toolSettings.template.toggle")}
        />
      </CardHeader>
    </Card>
  );
};
