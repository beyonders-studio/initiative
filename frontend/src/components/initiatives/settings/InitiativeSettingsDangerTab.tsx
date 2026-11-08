import { Archive, ArchiveRestore, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/ui/card";

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
    <div>
      <Card className="border-destructive/50">
        <CardHeader>
          <CardDescription>{t("settings.dangerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {canArchiveInitiative ? (
            <div className="space-y-2">
              <p className="text-muted-foreground text-sm">
                {isArchived ? t("settings.archivedDescription") : t("settings.archiveDescription")}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={onToggleArchive}
                pending={isArchiving}
              >
                {isArchived ? (
                  <ArchiveRestore className="h-4 w-4" />
                ) : (
                  <Archive className="h-4 w-4" />
                )}
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
        </CardContent>
      </Card>
    </div>
  );
};
