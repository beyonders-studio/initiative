import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeRead,
  InitiativeRoleRead,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  EXTRA_PERMISSION_KEYS,
  PERMISSION_LABEL_KEYS,
  useDeleteRole,
  useInitiativeDefaults,
  useInitiativeRoles,
  useUpdateRole,
} from "@/hooks/useInitiativeRoles";
import {
  isToolEnabled,
  SIDEBAR_TOOLS,
  TOOL_ICONS,
  toolCamelPlural,
  toolCreatePermission,
  toolViewPermission,
} from "@/lib/tools";

/**
 * The initiative's tools, split by whether it actually uses them.
 *
 * A permission grants nothing while the initiative's master switch is off, so
 * the tools that are on are the ones worth reading. The rest are still worth
 * setting — turning the tool back on should not mean redoing the roles — but
 * they belong below a line, under one explanation rather than eight copies of
 * it. Ordered like the sidebar and the tool grid, so the three screens agree.
 */
const splitToolsForRoleEditing = (
  initiative: InitiativeRead | null
): { on: Tool[]; off: Tool[] } => {
  if (!initiative) return { on: [...SIDEBAR_TOOLS], off: [] };
  return {
    on: SIDEBAR_TOOLS.filter((tool) => isToolEnabled(tool, initiative)),
    off: SIDEBAR_TOOLS.filter((tool) => !isToolEnabled(tool, initiative)),
  };
};

interface InitiativeSettingsRolesTabProps {
  initiativeId: number;
  /** The initiative, so a row can say when its tool is turned off. */
  initiative: InitiativeRead | null;
  canManageMembers: boolean;
  onOpenCreateRoleDialog: () => void;
  onDeleteRole: (role: InitiativeRoleRead) => void;
  onRenameRole: (role: InitiativeRoleRead) => void;
}

const NOTHING_LOCKED: ReadonlySet<string> = new Set();

/**
 * One tool, one row: what this role may see, and what it may make.
 *
 * The two used to be separate full-width rows, which made eight tools into
 * sixteen lines and put a tool's own pair of answers a screen apart. They
 * belong together — reading "view on, create off" is the whole question.
 */
const ToolPermissionRow = ({
  tool,
  role,
  canManageMembers,
  isPending,
  locked,
  onToggle,
  t,
}: {
  tool: Tool;
  role: InitiativeRoleRead;
  canManageMembers: boolean;
  isPending: boolean;
  /** The permissions the community set for this role: shown, not changed. */
  locked: ReadonlySet<string>;
  onToggle: (
    role: InitiativeRoleRead,
    tool: Tool,
    permission: "view" | "create",
    on: boolean
  ) => void;
  t: (key: never) => string;
}) => {
  const Icon = TOOL_ICONS[tool];
  const viewKey = toolViewPermission(tool) as PermissionKey;
  const createKey = toolCreatePermission(tool) as PermissionKey;
  const canView = role.permissions[viewKey] ?? false;
  const canCreate = role.permissions[createKey] ?? false;
  const disabled = !canManageMembers || isPending;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="min-w-0 flex-1 font-medium text-sm">
        {t(`settings.permissionGroups.${toolCamelPlural(tool)}` as never)}
      </span>
      <div className="flex items-center gap-4">
        {(
          [
            ["view", canView, viewKey],
            ["create", canCreate, createKey],
          ] as const
        ).map(([permission, checked, key]) => (
          // A span, not a label: the control is Radix's switch (a button),
          // which a label cannot caption. Its name comes from aria-label.
          <span key={permission} className="flex items-center gap-1.5">
            <span className="text-muted-foreground text-xs">
              {t(`settings.permissions.${permission}Short` as never)}
            </span>
            <Switch
              checked={checked}
              disabled={disabled || locked.has(key)}
              aria-label={t(PERMISSION_LABEL_KEYS[key] as never)}
              onCheckedChange={(next) => onToggle(role, tool, permission, next)}
            />
          </span>
        ))}
      </div>
    </div>
  );
};

/** A role that holds everything by construction — a card that says so, rather
 *  than a full set of switches nobody can move. */
const ManagerRoleCard = ({
  role,
  description,
  canManageMembers,
  isPending,
  onRenameRole,
  onDeleteRole,
  isDeleting,
  t,
}: {
  role: InitiativeRoleRead;
  description: string;
  canManageMembers: boolean;
  isPending: boolean;
  onRenameRole: (role: InitiativeRoleRead) => void;
  /** A custom manager role is still somebody's to delete — only the built-in
   *  ones are permanent, and only while nobody holds them. */
  onDeleteRole: (role: InitiativeRoleRead) => void;
  isDeleting: boolean;
  t: (key: never, opts?: Record<string, unknown>) => string;
}) => (
  <Card>
    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
      <div className="flex flex-wrap items-center gap-2">
        <CardTitle className="text-base">{role.display_name}</CardTitle>
        {role.is_builtin && (
          <Badge variant="secondary" className="text-xs">
            {t("settings.builtIn" as never)}
          </Badge>
        )}
        {/* "Full access" is the share override — reaching every item however
            each one is shared. A project manager holds every tool permission
            without it, so it is a manager and says so. */}
        {role.override_share_restrictions ? (
          <Badge className="text-xs">{t("settings.fullAccess" as never)}</Badge>
        ) : (
          <Badge variant="outline" className="text-xs">
            {t("settings.manager" as never)}
          </Badge>
        )}
        <Badge variant="outline" className="text-xs">
          {t("settings.memberCountBadge" as never, { count: role.member_count })}
        </Badge>
      </div>
      {canManageMembers && (
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" onClick={() => onRenameRole(role)} disabled={isPending}>
            <Pencil className="h-4 w-4" />
          </Button>
          {!role.is_builtin && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDeleteRole(role)}
              disabled={isDeleting || role.member_count > 0}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          )}
        </div>
      )}
    </CardHeader>
    <CardContent>
      <p className="text-muted-foreground text-sm">{description}</p>
    </CardContent>
  </Card>
);

export const InitiativeSettingsRolesTab = ({
  initiativeId,
  initiative,
  canManageMembers,
  onOpenCreateRoleDialog,
  onDeleteRole,
  onRenameRole,
}: InitiativeSettingsRolesTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  const rolesQuery = useInitiativeRoles(initiativeId || null);
  // What the community set for every initiative: the built-in member role's
  // permissions it set are shown, not changed, and it may keep initiatives to
  // their built-in roles.
  const defaults = useInitiativeDefaults().data;
  const memberLocked = new Set(Object.keys(defaults?.member_permissions ?? {}));
  const lockedFor = (role: InitiativeRoleRead): ReadonlySet<string> =>
    role.is_builtin && role.name === "member" ? memberLocked : NOTHING_LOCKED;
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const tools = splitToolsForRoleEditing(initiative);

  // Every manager role holds every permission by construction, so each gets a
  // card that says what it is. Project Manager used to render sixteen switches
  // that were pinned on and could not be moved — half a screen of controls
  // whose only job was to be refused.
  const managerRoles = (rolesQuery.data ?? []).filter((role) => role.is_manager);
  const configurableRoles = (rolesQuery.data ?? []).filter((role) => !role.is_manager);

  const handleTogglePermission = useCallback(
    (role: InitiativeRoleRead, tool: Tool, permission: "view" | "create", on: boolean) => {
      if (role.is_manager) return;
      const viewKey = toolViewPermission(tool) as PermissionKey;
      const createKey = toolCreatePermission(tool) as PermissionKey;
      // The pair moves together where the other answer would be incoherent:
      // making something you cannot see is not a state worth being able to
      // express, so granting create grants view, and revoking view revokes
      // create. One PATCH, so the role is never briefly in the odd state.
      const permissions = { ...role.permissions };
      if (permission === "view") {
        permissions[viewKey] = on;
        if (!on) permissions[createKey] = false;
      } else {
        permissions[createKey] = on;
        if (on) permissions[viewKey] = true;
      }
      updateRoleMutation.mutate({ roleId: role.id, data: { permissions } });
    },
    [updateRoleMutation]
  );

  const translate = t as unknown as (key: never, opts?: Record<string, unknown>) => string;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-semibold text-lg">{t("settings.rolesTitle")}</h3>
        <p className="text-muted-foreground text-sm">{t("settings.rolesDescription")}</p>
      </div>

      {rolesQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("settings.loadingRoles")}
        </div>
      ) : rolesQuery.data ? (
        <>
          {/* The roles there is nothing to configure, stated once and together
              rather than one full-width card over a grid of a different kind. */}
          {managerRoles.length > 0 && (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(min(20rem,100%),1fr))] gap-4">
              {managerRoles.map((role) => (
                <ManagerRoleCard
                  key={role.id}
                  role={role}
                  description={
                    role.name === "moderator"
                      ? t("settings.moderatorDescription")
                      : t("settings.managerDescription")
                  }
                  canManageMembers={canManageMembers}
                  isPending={updateRoleMutation.isPending}
                  onRenameRole={onRenameRole}
                  onDeleteRole={onDeleteRole}
                  isDeleting={deleteRoleMutation.isPending}
                  t={translate}
                />
              ))}
            </div>
          )}

          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(22rem,100%),1fr))] gap-4">
            {configurableRoles.map((role) => (
              <Card key={role.id}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-base">{role.display_name}</CardTitle>
                    {role.is_builtin && (
                      <Badge variant="secondary" className="text-xs">
                        {t("settings.builtIn")}
                      </Badge>
                    )}
                    <Badge variant="outline" className="text-xs">
                      {t("settings.memberCountBadge", { count: role.member_count })}
                    </Badge>
                  </div>
                  {canManageMembers && (
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onRenameRole(role)}
                        disabled={updateRoleMutation.isPending}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      {!role.is_builtin && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => onDeleteRole(role)}
                          disabled={deleteRoleMutation.isPending || role.member_count > 0}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      )}
                    </div>
                  )}
                </CardHeader>
                <CardContent className="space-y-3">
                  {lockedFor(role).size > 0 && (
                    <p className="text-muted-foreground text-xs">{t("settings.setByCommunity")}</p>
                  )}
                  {/* One list of every tool the initiative uses. Projects and
                      files used to sit above a section headed "Tools",
                      which taught a split the app no longer has — they are
                      tools like the other six. */}
                  {tools.on.map((tool) => (
                    <ToolPermissionRow
                      key={tool}
                      tool={tool}
                      role={role}
                      canManageMembers={canManageMembers}
                      isPending={updateRoleMutation.isPending}
                      locked={lockedFor(role)}
                      onToggle={handleTogglePermission}
                      t={translate}
                    />
                  ))}

                  {/* Capabilities inside a tool rather than the tool itself. */}
                  {EXTRA_PERMISSION_KEYS.map((key) => (
                    <div key={key} className="flex items-center gap-2 border-t pt-3">
                      <span className="min-w-0 flex-1 text-sm">
                        {t(PERMISSION_LABEL_KEYS[key] as never)}
                      </span>
                      <Switch
                        checked={role.permissions[key] ?? false}
                        disabled={
                          !canManageMembers ||
                          updateRoleMutation.isPending ||
                          lockedFor(role).has(key)
                        }
                        aria-label={t(PERMISSION_LABEL_KEYS[key] as never)}
                        onCheckedChange={(on) =>
                          updateRoleMutation.mutate({
                            roleId: role.id,
                            data: { permissions: { ...role.permissions, [key]: on } },
                          })
                        }
                      />
                    </div>
                  ))}

                  {tools.off.length > 0 && (
                    // Below a line, under one explanation. These are still
                    // worth setting — turning a tool back on should not mean
                    // redoing the roles — they just grant nothing yet.
                    <div className="space-y-3 border-t pt-3">
                      <div>
                        <h4 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
                          {t("settings.toolAudience.turnedOffHeading")}
                        </h4>
                        <p className="mt-1 text-muted-foreground text-xs">
                          {t("settings.toolAudience.turnedOffNote")}
                        </p>
                      </div>
                      <div className="space-y-3 opacity-60">
                        {tools.off.map((tool) => (
                          <ToolPermissionRow
                            key={tool}
                            tool={tool}
                            role={role}
                            canManageMembers={canManageMembers}
                            isPending={updateRoleMutation.isPending}
                            locked={lockedFor(role)}
                            onToggle={handleTogglePermission}
                            t={translate}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      ) : null}

      {canManageMembers &&
        (defaults?.custom_roles === false ? (
          <p className="text-muted-foreground text-sm">{t("settings.customRolesOff")}</p>
        ) : (
          <Button variant="outline" onClick={onOpenCreateRoleDialog}>
            <Plus className="h-4 w-4" />
            {t("settings.addCustomRole")}
          </Button>
        ))}
    </div>
  );
};
