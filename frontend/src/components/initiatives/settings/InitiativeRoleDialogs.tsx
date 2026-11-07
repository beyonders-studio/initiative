/**
 * The three dialogs the Roles section opens: create a role, rename one, delete
 * one. They live with the section that opens them, so a section route carries
 * its own modals rather than a shared bundle carrying everyone's.
 */

import { Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRoleRead } from "@/api/generated/initiativeAPI.schemas";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateRole, useDeleteRole, useUpdateRole } from "@/hooks/useInitiativeRoles";
import { toast } from "@/lib/mascotToast";

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
            <div className="space-y-2">
              <Label htmlFor="new-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="new-role-display-name"
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
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-role-name">{t("settings.roleInternalNameLabel")}</Label>
              <Input
                id="new-role-name"
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
              <p className="text-muted-foreground text-xs">{t("settings.roleInternalNameHint")}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewRoleDialog(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={handleCreateRole}
              disabled={
                createRoleMutation.isPending || !newRoleName.trim() || !newRoleDisplayName.trim()
              }
            >
              {createRoleMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("settings.creatingRole")}
                </>
              ) : (
                t("settings.createRole")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Role Confirmation Dialog */}
      <AlertDialog open={!!roleToDelete} onOpenChange={(open) => !open && setRoleToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteRoleTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.deleteRoleDescription", { roleName: roleToDelete?.display_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRoleMutation.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteRole}
              disabled={deleteRoleMutation.isPending}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {deleteRoleMutation.isPending ? t("settings.deletingRole") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
            <div className="space-y-2">
              <Label htmlFor="rename-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="rename-role-display-name"
                value={renameDisplayName}
                onChange={(e) => setRenameDisplayName(e.target.value)}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleToRename(null)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={confirmRenameRole}
              disabled={updateRoleMutation.isPending || !renameDisplayName.trim()}
            >
              {updateRoleMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("settings.savingRole")}
                </>
              ) : (
                t("common:save")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
