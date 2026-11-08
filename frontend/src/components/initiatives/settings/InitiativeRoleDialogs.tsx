/**
 * The three dialogs the Roles section opens: create a role, rename one, delete
 * one. They live with the section that opens them, so a section route carries
 * its own modals rather than a shared bundle carrying everyone's.
 */

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead } from "@/api/generated/initiativeAPI.schemas";
import { useCreateRole, useDeleteRole, useUpdateRole } from "@/hooks/useInitiativeRoles";
import { toast } from "@/lib/mascotToast";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

export interface InitiativeRoleDialogsProps {
  initiativeId: number;
  showNewRoleDialog: boolean;
  setShowNewRoleDialog: (open: boolean) => void;
  roleToDelete: InitiativeRoleRead | null;
  setRoleToDelete: (role: InitiativeRoleRead | null) => void;
  roleToRename: InitiativeRoleRead | null;
  setRoleToRename: (role: InitiativeRoleRead | null) => void;
}

export const InitiativeRoleDialogs = ({
  initiativeId,
  showNewRoleDialog,
  setShowNewRoleDialog,
  roleToDelete,
  setRoleToDelete,
  roleToRename,
  setRoleToRename,
}: InitiativeRoleDialogsProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  // New role dialog state
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDisplayName, setNewRoleDisplayName] = useState("");
  const roleNameTouchedRef = useRef(false);

  // Rename role dialog state
  const [renameDisplayName, setRenameDisplayName] = useState(roleToRename?.display_name ?? "");

  // Sync renameDisplayName when roleToRename changes
  const [prevRoleToRename, setPrevRoleToRename] = useState(roleToRename);
  if (prevRoleToRename !== roleToRename) {
    setPrevRoleToRename(roleToRename);
    if (roleToRename) {
      setRenameDisplayName(roleToRename.display_name);
    }
  }

  const createRoleMutation = useCreateRole(initiativeId);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const handleCreateRole = () => {
    const name = newRoleName.trim().toLowerCase().replace(/\s+/g, "_");
    const displayName = newRoleDisplayName.trim();
    if (!name || !displayName) {
      toast.error(t("settings.roleNameRequired"));
      return;
    }
    createRoleMutation.mutate(
      { name, display_name: displayName },
      {
        onSuccess: () => {
          setShowNewRoleDialog(false);
          setNewRoleName("");
          setNewRoleDisplayName("");
          roleNameTouchedRef.current = false;
        },
      }
    );
  };

  const confirmDeleteRole = () => {
    if (roleToDelete) {
      deleteRoleMutation.mutate(roleToDelete.id, {
        onSuccess: () => setRoleToDelete(null),
      });
    }
  };

  const confirmRenameRole = () => {
    if (roleToRename && renameDisplayName.trim()) {
      updateRoleMutation.mutate(
        { roleId: roleToRename.id, data: { display_name: renameDisplayName.trim() } },
        { onSuccess: () => setRoleToRename(null) }
      );
    }
  };

  return (
    <>
      {/* New Role Dialog */}
      <Dialog
        open={showNewRoleDialog}
        onOpenChange={(open) => {
          setShowNewRoleDialog(open);
          if (!open) roleNameTouchedRef.current = false;
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.createRoleTitle")}</DialogTitle>
            <DialogDescription>{t("settings.createRoleDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <Field label={t("settings.roleDisplayNameLabel")}>
              <Input
                value={newRoleDisplayName}
                onChange={(e) => {
                  const display = e.target.value;
                  setNewRoleDisplayName(display);
                  if (!roleNameTouchedRef.current) {
                    setNewRoleName(
                      display
                        .trim()
                        .toLowerCase()
                        .replace(/\s+/g, "_")
                        .replace(/[^a-z0-9_]/g, "")
                    );
                  }
                }}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </Field>
            <Field
              label={t("settings.roleInternalNameLabel")}
              hint={t("settings.roleInternalNameHint")}
            >
              <Input
                value={newRoleName}
                onChange={(e) => {
                  const snakeCase = e.target.value
                    .toLowerCase()
                    .replace(/\s+/g, "_")
                    .replace(/[^a-z0-9_]/g, "");
                  setNewRoleName(snakeCase);
                  if (!snakeCase && !newRoleDisplayName) {
                    roleNameTouchedRef.current = false;
                  } else {
                    roleNameTouchedRef.current = true;
                  }
                }}
                placeholder={t("settings.roleInternalNamePlaceholder")}
              />
            </Field>
          </div>
          <DialogFooter
            submitLabel={t("settings.createRole")}
            pendingLabel={t("settings.creatingRole")}
            onSubmit={handleCreateRole}
            pending={createRoleMutation.isPending}
            disabled={!newRoleName.trim() || !newRoleDisplayName.trim()}
          />
        </DialogContent>
      </Dialog>

      {/* Delete Role Confirmation Dialog */}
      <ConfirmDialog
        open={!!roleToDelete}
        onOpenChange={(open) => !open && setRoleToDelete(null)}
        title={t("settings.deleteRoleTitle")}
        description={t("settings.deleteRoleDescription", { roleName: roleToDelete?.display_name })}
        confirmLabel={t("common:delete")}
        loadingLabel={t("settings.deletingRole")}
        isLoading={deleteRoleMutation.isPending}
        destructive
        onConfirm={confirmDeleteRole}
      />

      {/* Rename Role Dialog */}
      <Dialog open={!!roleToRename} onOpenChange={(open) => !open && setRoleToRename(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.renameRoleTitle")}</DialogTitle>
            <DialogDescription>
              {t("settings.renameRoleDescription", { roleName: roleToRename?.display_name })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <Field label={t("settings.roleDisplayNameLabel")}>
              <Input
                value={renameDisplayName}
                onChange={(e) => setRenameDisplayName(e.target.value)}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </Field>
          </div>
          <DialogFooter
            submitLabel={t("common:save")}
            pendingLabel={t("settings.savingRole")}
            onSubmit={confirmRenameRole}
            pending={updateRoleMutation.isPending}
            disabled={!renameDisplayName.trim()}
          />
        </DialogContent>
      </Dialog>
    </>
  );
};
