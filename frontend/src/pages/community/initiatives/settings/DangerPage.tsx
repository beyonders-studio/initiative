import { useRouter } from "@tanstack/react-router";
import { Archive, ArchiveRestore, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useDeleteInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
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

const InitiativeSettingsDangerTab = ({
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

export const DangerPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const gp = useCommunityPath();
  const router = useRouter();
  const { initiativeId, initiative, canManageMembers, canDeleteInitiative, isCommunityAdmin } =
    useInitiativeSettings();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const archiveInitiative = useArchiveEntity();
  const unarchiveInitiative = useUnarchiveEntity();

  const deleteInitiative = useDeleteInitiative({
    onSuccess: () => {
      toast.success(t("settings.deleted"));
      router.navigate({ to: gp("/") });
    },
  });

  if (!canManageMembers && !canDeleteInitiative) {
    return <SettingsPermissionRequired scope="initiative" />;
  }

  if (!initiative) {
    return null;
  }

  return (
    <>
      <InitiativeSettingsDangerTab
        isArchived={initiative.archived_at !== null}
        canArchiveInitiative={isCommunityAdmin}
        isArchiving={archiveInitiative.isPending || unarchiveInitiative.isPending}
        onToggleArchive={() =>
          (initiative.archived_at === null ? archiveInitiative : unarchiveInitiative).mutate({
            entityType: "initiative",
            entityId: initiativeId,
          })
        }
        canDeleteInitiative={canDeleteInitiative}
        isDeleting={deleteInitiative.isPending}
        onDeleteInitiative={() => setShowDeleteConfirm(true)}
      />
      {/* Shared with the community settings Initiatives table, so there is a single
          delete workflow. */}
      <DeleteInitiativeDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        initiativeName={initiative.name}
        isDeleting={deleteInitiative.isPending}
        onConfirm={() => {
          deleteInitiative.mutate(initiativeId);
          setShowDeleteConfirm(false);
        }}
      />
    </>
  );
};
