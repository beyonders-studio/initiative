/**
 * `/settings/roles` — what each role may do inside this initiative, and the
 * dialogs for adding, renaming, and removing one.
 */

import { useState } from "react";

import type { InitiativeRoleRead } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeRoleDialogs } from "@/components/initiatives/settings/InitiativeRoleDialogs";
import { InitiativeSettingsRolesTab } from "@/components/initiatives/settings/InitiativeSettingsRolesTab";
import { SettingsPermissionRequired } from "@/components/settings/SettingsPermissionRequired";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";

export const InitiativeSettingsRolesPage = () => {
  const { initiativeId, initiative, canManageMembers } = useInitiativeSettings();

  const [showNewRoleDialog, setShowNewRoleDialog] = useState(false);
  const [roleToDelete, setRoleToDelete] = useState<InitiativeRoleRead | null>(null);
  const [roleToRename, setRoleToRename] = useState<InitiativeRoleRead | null>(null);

  if (!canManageMembers) {
    return <SettingsPermissionRequired scope="initiative" />;
  }

  return (
    <>
      <InitiativeSettingsRolesTab
        initiativeId={initiativeId}
        initiative={initiative}
        canManageMembers={canManageMembers}
        onOpenCreateRoleDialog={() => setShowNewRoleDialog(true)}
        onDeleteRole={setRoleToDelete}
        onRenameRole={setRoleToRename}
      />
      <InitiativeRoleDialogs
        initiativeId={initiativeId}
        showNewRoleDialog={showNewRoleDialog}
        setShowNewRoleDialog={setShowNewRoleDialog}
        roleToDelete={roleToDelete}
        setRoleToDelete={setRoleToDelete}
        roleToRename={roleToRename}
        setRoleToRename={setRoleToRename}
      />
    </>
  );
};
