import { Archive, ArchiveRestore, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/ui/button";

interface InitiativeSettingsDangerTabProps {
  isArchived: boolean;
  // Archiving (hide from the sidebar) is a community-admin-only action.
  canArchiveInitiative: boolean;
  isArchiving: boolean;
  onToggleArchive: () => void;
  canDeleteInitiative: boolean;
  isDeleting: boolean;
  onDeleteInitiative: () => void;
}

export const InitiativeSettingsDangerTab = ({
  isArchived,
  canArchiveInitiative,
  isArchiving,
  onToggleArchive,
  canDeleteInitiative,
  isDeleting,
  onDeleteInitiative,
}: InitiativeSettingsDangerTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  return (
    <SettingsSection destructive description={t("settings.dangerDescription")}>
      {canArchiveInitiative ? (
        <div className="space-y-2">
          <p className="text-muted-foreground text-sm">
            {isArchived ? t("settings.archivedDescription") : t("settings.archiveDescription")}
          </p>
          <Button type="button" variant="outline" onClick={onToggleArchive} pending={isArchiving}>
            {isArchived ? <ArchiveRestore className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
            {isArchived ? t("settings.unarchiveInitiative") : t("settings.archiveInitiative")}
          </Button>
        </div>
      ) : null}
      {canArchiveInitiative && canDeleteInitiative ? <div className="h-px bg-border" /> : null}
      {canDeleteInitiative ? (
        <Button
          type="button"
          variant="destructive"
          onClick={onDeleteInitiative}
          pending={isDeleting}
        >
          <Trash2 className="h-4 w-4" />
          {isDeleting ? t("settings.deletingInitiative") : t("settings.deleteInitiative")}
        </Button>
      ) : (
        <p className="text-muted-foreground text-sm">{t("settings.contactAdmin")}</p>
      )}
    </SettingsSection>
  );
};
