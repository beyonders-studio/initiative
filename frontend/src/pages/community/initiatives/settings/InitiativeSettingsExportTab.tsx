import { FileDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ExportWizard } from "@/components/exports/ExportWizard";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/ui/button";
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

  return (
    <div className="space-y-6">
      <SettingsSection
        title={t("initiatives:settings.keepContentIn.title")}
        description={t("initiatives:settings.keepContentIn.help")}
      >
        <SettingsRow label={t("initiatives:settings.keepContentIn.label")}>
          <Switch
            checked={keepContentIn}
            disabled={isSaving}
            onCheckedChange={onChangeKeepContentIn}
          />
        </SettingsRow>
      </SettingsSection>
      <SettingsSection description={t("entry.initiativeDescription")}>
        <Button onClick={() => setWizardOpen(true)}>
          <FileDown className="h-4 w-4" />
          {t("entry.open")}
        </Button>
      </SettingsSection>
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
