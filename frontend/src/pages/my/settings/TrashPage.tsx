import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { TrashTable } from "@/components/trash/TrashTable";

export const TrashPage = () => {
  const { t } = useTranslation("trash");

  return (
    <SettingsSection description={t("description")}>
      {/* Personal, cross-community "my deletions" view (/me/trash). The
          Delete-now purge button is hidden — that action is admin-only and is
          reached through the community Settings → Trash tab instead. */}
      <TrashTable variant="user" showPurgeAction={false} />
    </SettingsSection>
  );
};
