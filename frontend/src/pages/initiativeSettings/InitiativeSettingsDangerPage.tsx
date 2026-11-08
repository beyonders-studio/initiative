/**
 * `/settings/danger` — archiving the initiative, and deleting it.
 *
 * Both actions are the community admin's: the section itself is readable by anyone
 * who may configure the initiative (it explains what archiving and deletion
 * mean, and who to ask), while each control stays gated on the standing it
 * actually needs.
 */

import { useRouter } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { InitiativeSettingsDangerTab } from "@/components/initiatives/settings/InitiativeSettingsDangerTab";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useDeleteInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";

export const InitiativeSettingsDangerPage = () => {
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
