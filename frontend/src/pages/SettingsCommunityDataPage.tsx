import { FileUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityExportCard } from "@/components/exports/CommunityExportCard";
import { DataJobsTable } from "@/components/imports/DataJobsTable";
import { ImportWizard } from "@/components/imports/ImportWizard";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/ui/button";

export const SettingsCommunityDataPage = () => {
  const { t } = useTranslation(["exports", "imports"]);
  const [importOpen, setImportOpen] = useState(false);

  // The tab is offered to the seat alone, and the backend re-checks it at
  // request AND apply time — taking the whole community out in one file, or
  // putting one back, is not an errand an ordinary admin runs.
  return (
    <div className="space-y-6">
      <CommunityExportCard />
      <SettingsSection
        title={t("imports:dataTab.importTitle")}
        description={t("imports:dataTab.importDescription")}
      >
        <Button onClick={() => setImportOpen(true)}>
          <FileUp className="h-4 w-4" />
          {t("imports:dataTab.open")}
        </Button>
      </SettingsSection>
      <SettingsSection
        title={t("exports:table.title")}
        description={t("exports:table.description")}
      >
        <DataJobsTable />
      </SettingsSection>
      {/* Mounted outside the open check so a job started in the wizard keeps
          polling (and delivers its outcome) after the dialog closes. */}
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
};
