import { Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type AdminSurface,
  CommunityRole,
  type CustomRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
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
import { Alert, AlertDescription } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/ui/dropdown-menu";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

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

  const [prev, setPrev] = useState({ open, role });
  if (prev.open !== open || prev.role !== role) {
    setPrev({ open, role });
    if (open) {
      setName(role?.name ?? "");
      setRung(role?.base_rung === "admin" ? "admin" : "member");
      setSurfaces(role?.surfaces ?? []);
    }
  }

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
          <Field label={t("customRoles.nameLabel")}>
            <Input
              value={name}
              maxLength={MAX_NAME_LENGTH}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </Field>
          <Field
            label={t("customRoles.rungLabel")}
            hint={role ? t("customRoles.rungFixed") : t(`customRoles.rungHelp.${rung}`)}
          >
            <Select
              value={rung}
              onValueChange={(value) => setRung(value as Rung)}
              disabled={Boolean(role)}
            >
              <SelectTrigger className="w-full max-w-72">
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
          </Field>
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
          <DialogFooter
            submitLabel={role ? t("common:save") : t("customRoles.add")}
            pending={pending}
            disabled={!name.trim()}
          />
        </form>
      </DialogContent>
    </Dialog>
  );
};

/**
 * Community settings › Roles: the roles every community has, then its custom
 * ones. A role on the member rung gives a member some parts of running the
 * community; one on the admin rung narrows an admin to the parts it lists.
 */
export const SettingsCommunityRolesPage = () => {
  const { t } = useTranslation(["settings", "communities", "common"]);
  const { activeCommunity } = useCommunities();
  const { guestsEnabled } = useAppConfig();
  const held = useHeldSurfaces();
  // Highest first. Guests only where the deployment allows them and the
  // community takes any, as on the Guests tab.
  const builtInRoles: CommunityRole[] = [
    CommunityRole.superadmin,
    CommunityRole.admin,
    CommunityRole.member,
    ...(guestsEnabled && activeCommunity?.max_guests !== 0 ? [CommunityRole.guest] : []),
  ];
  const rolesQuery = useCustomRoles({ enabled: held.holds("roles") });
  const deleteRole = useDeleteCustomRole();
  // `null` closed; `"new"` adds one.
  const [editing, setEditing] = useState<CustomRoleRead | "new" | null>(null);
  const [deleting, setDeleting] = useState<CustomRoleRead | null>(null);

  // The deployment may close custom roles for a community; the roles it has
  // keep applying, and nobody changes them.
  const closed = Boolean(activeCommunity?.closed_surfaces?.includes("custom_roles"));
  const changes = held.writes && !closed;
  // A role the deployment defined is given here, and changed only by it.
  const fromDeployment = (role: CustomRoleRead) => role.set_by === "deployment";

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
      <SettingsSection
        title={t("customRoles.title")}
        description={t("customRoles.description")}
        action={addButton}
      >
        {closed ? (
          <Alert>
            <AlertDescription>{t("customRoles.closed")}</AlertDescription>
          </Alert>
        ) : null}
        <ul className="divide-y rounded-md border">
          {builtInRoles.map((role) => (
            <li key={role} className="space-y-1.5 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">
                  {t(`communities:users.communityRole.${role}` as never)}
                </p>
                <Badge variant="secondary" className="font-normal">
                  {t("customRoles.builtIn")}
                </Badge>
              </div>
              <p className="text-muted-foreground text-xs">
                {t(`communities:users.communityRoleHelp.${role}` as never)}
              </p>
            </li>
          ))}
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
                  <p className="text-muted-foreground text-xs">{t("customRoles.holdsNothing")}</p>
                )}
                {fromDeployment(role) ? (
                  <p className="text-muted-foreground text-xs">
                    {t("customRoles.setByDeployment")}
                  </p>
                ) : changes && !held.gives(role) ? (
                  <p className="text-muted-foreground text-xs">{t("customRoles.beyondYours")}</p>
                ) : changes && !held.takesOff(role) ? (
                  <p className="text-muted-foreground text-xs">{t("customRoles.widensAnAdmin")}</p>
                ) : null}
              </div>
              {changes && held.gives(role) && !fromDeployment(role) ? (
                <RowActionsMenu subject={role.name}>
                  <DropdownMenuItem onSelect={() => setEditing(role)}>
                    <Pencil className="h-4 w-4" />
                    {t("common:edit")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    disabled={!held.takesOff(role)}
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
        {rolesQuery.isLoading ? (
          <SkeletonRegion label={t("customRoles.loading")}>
            <ListSkeleton rows={2} avatar={false} />
          </SkeletonRegion>
        ) : rolesQuery.isError ? (
          <p className="text-destructive text-sm">{t("customRoles.loadError")}</p>
        ) : null}
      </SettingsSection>

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
