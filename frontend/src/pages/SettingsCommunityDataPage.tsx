import { FileUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityExportCard } from "@/components/exports/CommunityExportCard";
import { DataJobsTable } from "@/components/imports/DataJobsTable";
import { ImportWizard } from "@/components/imports/ImportWizard";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

export const SettingsCommunityDataPage = () => {
  const { t } = useTranslation(["exports", "imports"]);
  const [importOpen, setImportOpen] = useState(false);

  // The tab is offered to the seat alone, and the backend re-checks it at
  // request AND apply time — taking the whole community out in one file, or
  // putting one back, is not an errand an ordinary admin runs.
  return (
    <div className="space-y-6">
      <CommunityExportCard />
      <Card>
        <CardHeader>
          <CardTitle>{t("imports:dataTab.importTitle")}</CardTitle>
          <CardDescription>{t("imports:dataTab.importDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => setImportOpen(true)}>
            <FileUp className="h-4 w-4" />
            {t("imports:dataTab.open")}
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("exports:table.title")}</CardTitle>
          <CardDescription>{t("exports:table.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <DataJobsTable />
        </CardContent>
      </Card>
      {/* Mounted outside the open check so a job started in the wizard keeps
          polling (and delivers its outcome) after the dialog closes. */}
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
};

export default SettingsCommunityDataPage;
