import { Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AdminSurface,
  CommunityRole,
  CustomRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ListSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCommunities } from "@/hooks/useCommunities";
import {
  ADMIN_SURFACES,
  MEMBER_ROLE_SURFACES,
  useCreateCustomRole,
  useCustomRoles,
  useDeleteCustomRole,
  useHeldSurfaces,
  useUpdateCustomRole,
} from "@/hooks/useCustomRoles";
import type { DialogProps } from "@/types/dialog";

/** The longest name the server takes. */
const MAX_NAME_LENGTH = 64;

type Rung = Extract<CommunityRole, "member" | "admin">;

const offeredSurfaces = (rung: Rung): readonly AdminSurface[] =>
  rung === "member" ? MEMBER_ROLE_SURFACES : ADMIN_SURFACES;

interface CustomRoleDialogProps extends DialogProps {
  /** The role being edited; left out, the dialog adds one. */
  role?: CustomRoleRead;
}

/** Add a role, or change one's name and what it holds. Its rung is set once. */
const CustomRoleDialog = ({ role, open, onOpenChange }: CustomRoleDialogProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const { activeCommunity } = useCommunities();
  const held = useHeldSurfaces();
  const createRole = useCreateCustomRole();
  const updateRole = useUpdateCustomRole();
  const [name, setName] = useState("");
  const [rung, setRung] = useState<Rung>("member");
  const [surfaces, setSurfaces] = useState<AdminSurface[]>([]);

  useEffect(() => {
    if (!open) return;
    setName(role?.name ?? "");
    setRung(role?.base_rung === "admin" ? "admin" : "member");
    setSurfaces(role?.surfaces ?? []);
  }, [open, role]);

  const offered = offeredSurfaces(rung);
  const pending = createRole.isPending || updateRole.isPending;
  const close = () => onOpenChange(false);

  const toggle = (surface: AdminSurface, checked: boolean) =>
    setSurfaces((current) =>
      checked ? [...current, surface] : current.filter((value) => value !== surface)
    );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Only what the rung offers: a member role never carries an admin's part.
    const sent = surfaces.filter((surface) => offered.includes(surface));
    if (role) {
      updateRole.mutate(
        { roleId: role.id, data: { name: name.trim(), surfaces: sent } },
        { onSuccess: close }
      );
    } else {
      createRole.mutate(
        { name: name.trim(), base_rung: rung, surfaces: sent },
        { onSuccess: close }
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {role ? t("customRoles.editTitle", { name: role.name }) : t("customRoles.addTitle")}
          </DialogTitle>
          <DialogDescription>{t("customRoles.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="custom-role-name">{t("customRoles.nameLabel")}</Label>
            <Input
              id="custom-role-name"
              value={name}
              maxLength={MAX_NAME_LENGTH}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="custom-role-rung">{t("customRoles.rungLabel")}</Label>
            <Select
              value={rung}
              onValueChange={(value) => setRung(value as Rung)}
              disabled={Boolean(role)}
            >
              <SelectTrigger id="custom-role-rung" className="w-full max-w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">{t("customRoles.rung.member")}</SelectItem>
                {/* Only an admin makes a role for admins. */}
                <SelectItem value="admin" disabled={!activeCommunity?.can.administer}>
                  {t("customRoles.rung.admin")}
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {role ? t("customRoles.rungFixed") : t(`customRoles.rungHelp.${rung}`)}
            </p>
          </div>
          <fieldset className="space-y-3">
            <legend className="mb-2 font-medium text-sm">{t("customRoles.surfacesLabel")}</legend>
            {offered.map((surface) => {
              const id = `custom-role-surface-${surface}`;
              const yours = held.holds(surface);
              return (
                <div key={surface} className="flex items-start gap-3">
                  <Checkbox
                    id={id}
                    checked={surfaces.includes(surface)}
                    onCheckedChange={(checked) => toggle(surface, checked === true)}
                    disabled={!yours}
                    className="mt-0.5"
                  />
                  <div className="space-y-0.5">
                    <Label htmlFor={id} className="font-normal">
                      {t(`customRoles.surfaces.${surface}.label`)}
                    </Label>
                    <p className="text-muted-foreground text-xs">
                      {yours
                        ? t(`customRoles.surfaces.${surface}.description`)
                        : t("customRoles.notYours")}
                    </p>
                  </div>
                </div>
              );
            })}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={close}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" disabled={pending || !name.trim()}>
              {role ? t("common:save") : t("customRoles.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

/**
 * Community settings › Roles: the community's custom roles. A role on the
 * member rung gives a member some parts of running the community; one on the
 * admin rung narrows an admin to the parts it lists.
 */
export const SettingsCommunityRolesPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { activeCommunity } = useCommunities();
  const held = useHeldSurfaces();
  const rolesQuery = useCustomRoles({ enabled: held.holds("roles") });
  const deleteRole = useDeleteCustomRole();
  // `null` closed; `"new"` adds one.
  const [editing, setEditing] = useState<CustomRoleRead | "new" | null>(null);
  const [deleting, setDeleting] = useState<CustomRoleRead | null>(null);

  // The deployment may close custom roles for a community; the roles it has
  // keep applying, and nobody changes them.
  const closed = Boolean(activeCommunity?.closed_surfaces?.includes("custom_roles"));
  const changes = held.writes && !closed;
  // What the server allows, so nobody fills in a form it must refuse: a role
  // holding nothing the reader lacks, on the admin rung only for an admin, and
  // deleting an admin's role (which gives its holders everything back) only for
  // somebody who holds everything. A settings grant answers for itself.
  const lent = Boolean(activeCommunity?.grantSettingsLevel);
  const holdsEvery = ADMIN_SURFACES.every(held.holds);
  const editable = (role: CustomRoleRead) =>
    lent ||
    (role.surfaces.every(held.holds) &&
      (role.base_rung !== "admin" || Boolean(activeCommunity?.can.administer)));
  const deletable = (role: CustomRoleRead) =>
    editable(role) && (lent || role.base_rung !== "admin" || holdsEvery);

  if (!held.holds("roles")) {
    return <p className="text-muted-foreground text-sm">{t("communityLayout.permissionDenied")}</p>;
  }

  const roles = rolesQuery.data ?? [];
  const addButton = changes ? (
    <Button type="button" size="sm" onClick={() => setEditing("new")}>
      <Plus className="h-4 w-4" />
      {t("customRoles.add")}
    </Button>
  ) : null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>{t("customRoles.title")}</CardTitle>
            <CardDescription>{t("customRoles.description")}</CardDescription>
          </div>
          {roles.length > 0 ? addButton : null}
        </CardHeader>
        <CardContent className="space-y-4">
          {closed ? (
            <Alert>
              <AlertDescription>{t("customRoles.closed")}</AlertDescription>
            </Alert>
          ) : null}
          {rolesQuery.isLoading ? (
            <SkeletonRegion label={t("customRoles.loading")}>
              <ListSkeleton rows={2} avatar={false} />
            </SkeletonRegion>
          ) : rolesQuery.isError ? (
            <p className="text-destructive text-sm">{t("customRoles.loadError")}</p>
          ) : roles.length === 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-muted-foreground text-sm">{t("customRoles.empty")}</p>
              {addButton}
            </div>
          ) : (
            <ul className="divide-y rounded-md border">
              {roles.map((role) => (
                <li key={role.id} className="flex items-start justify-between gap-3 p-3">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{role.name}</p>
                      <span className="text-muted-foreground text-xs">
                        {t(`customRoles.rung.${role.base_rung === "admin" ? "admin" : "member"}`)}
                      </span>
                    </div>
                    {role.surfaces.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {role.surfaces.map((surface) => (
                          <Badge key={surface} variant="secondary" className="font-normal">
                            {t(`customRoles.surfaces.${surface}.label`)}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <p className="text-muted-foreground text-xs">
                        {t("customRoles.holdsNothing")}
                      </p>
                    )}
                    {changes && !editable(role) ? (
                      <p className="text-muted-foreground text-xs">
                        {t("customRoles.beyondYours")}
                      </p>
                    ) : changes && !deletable(role) ? (
                      <p className="text-muted-foreground text-xs">
                        {t("customRoles.widensAnAdmin")}
                      </p>
                    ) : null}
                  </div>
                  {changes && editable(role) ? (
                    <RowActionsMenu subject={role.name}>
                      <DropdownMenuItem onSelect={() => setEditing(role)}>
                        <Pencil className="h-4 w-4" />
                        {t("common:edit")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive"
                        disabled={!deletable(role)}
                        onSelect={() => setDeleting(role)}
                      >
                        <Trash2 className="h-4 w-4" />
                        {t("common:delete")}
                      </DropdownMenuItem>
                    </RowActionsMenu>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <CustomRoleDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        role={editing === "new" || editing === null ? undefined : editing}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("customRoles.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("customRoles.deleteDescription")}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        destructive
        isLoading={deleteRole.isPending}
        onConfirm={() => {
          if (!deleting) return;
          deleteRole.mutate(deleting.id, { onSuccess: () => setDeleting(null) });
        }}
      />
    </div>
  );
};
