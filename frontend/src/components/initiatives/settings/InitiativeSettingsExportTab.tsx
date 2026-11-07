import { FileDown } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportWizard } from "@/components/exports/ExportWizard";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

interface InitiativeSettingsExportTabProps {
  initiativeId: number;
  keepContentIn: boolean;
  onChangeKeepContentIn: (next: boolean) => void;
  isSaving: boolean;
}

export const InitiativeSettingsExportTab = ({
  initiativeId,
  keepContentIn,
  onChangeKeepContentIn,
  isSaving,
}: InitiativeSettingsExportTabProps) => {
  const { t } = useTranslation(["exports", "initiatives"]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const keepContentInId = useId();

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("initiatives:settings.keepContentIn.title")}</CardTitle>
          <CardDescription>{t("initiatives:settings.keepContentIn.help")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-3">
            <Switch
              id={keepContentInId}
              checked={keepContentIn}
              disabled={isSaving}
              onCheckedChange={onChangeKeepContentIn}
              className="mt-0.5"
            />
            <Label htmlFor={keepContentInId} className="font-medium">
              {t("initiatives:settings.keepContentIn.label")}
            </Label>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>{t("entry.initiativeDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setWizardOpen(true)}>
            <FileDown className="h-4 w-4" />
            {t("entry.open")}
          </Button>
        </CardContent>
      </Card>
      {/* Mounted outside the open check so a job started in the wizard keeps
          polling (and delivers its download) after the dialog closes. */}
      <ExportWizard
        scope={{ kind: "initiative", initiativeId }}
        open={wizardOpen}
        onOpenChange={setWizardOpen}
      />
    </div>
  );
};
