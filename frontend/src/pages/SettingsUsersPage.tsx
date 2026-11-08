import { Link } from "@tanstack/react-router";
import { Download, HandCoins, IdCard, RefreshCcw, UserMinus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityRole, type UserCommunityMember } from "@/api/generated/initiativeAPI.schemas";
import { MemberInvites } from "@/components/communities/CommunityInvites";
import { MemberDisplayNameDialog } from "@/components/communities/MemberDisplayNameDialog";
import { RemoveCommunityMemberDialog } from "@/components/communities/RemoveCommunityMemberDialog";
import { TransferContentOwnershipDialog } from "@/components/communities/TransferContentOwnershipDialog";
import { UnownedContentCard } from "@/components/communities/UnownedContentCard";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { UserHandle } from "@/components/UserHandle";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { useCommunityInvites } from "@/hooks/useCommunityInvites";
import {
  useAssignCustomRole,
  useCustomRoleHolders,
  useCustomRoles,
  useHeldSurfaces,
} from "@/hooks/useCustomRoles";
import { useServerTableState } from "@/hooks/useServerTableState";
import {
  useExportCommunityUsersCsv,
  useSetMemberApiAccess,
  useUpdateCommunityMembership,
  useUsers,
} from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { assignableCommunityRoles, isAdminRole } from "@/lib/permissions";
import { getUrlHandle, getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import { Button } from "@/ui/button";
import { DataTable } from "@/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/ui/dropdown-menu";
import type { AppColumnDef } from "@/ui/lib/table";
import { FormSkeleton, SkeletonRegion, TableSkeleton } from "@/ui/page-skeletons";
import { RowActionsMenu } from "@/ui/row-actions-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

//: The custom role picker's "none", since a select's value is a string.
const NO_CUSTOM_ROLE = "none";

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const { t } = useTranslation(["communities", "settings"]);

  const { activeCommunity } = useCommunities();
  // Running the community, not reaching its work: the roster and its
  // invites are parts of running it, held by its admins, by a custom role, or
  // by a settings grant standing in. Platform role has nothing to do with it.
  const held = useHeldSurfaces();
  const managesMembers = held.holds("members");
  // Invites are handed out by whoever holds them and may change what they
  // hold, so a grant that only reads does not list them.
  const managesInvites = held.writes && held.holds("invites");
  const opensPage = managesMembers || held.holds("invites");
  const roleOptions = assignableCommunityRoles(Boolean(activeCommunity?.can.seat));
  // Rungs are changed by whoever may make an admin, as on the members page.
  const changesRungs = held.writes && held.managesAdmins;

  const activeCommunityId = activeCommunity?.id ?? null;

  // Whose personal API keys reach the community is the seat's to say, and only
  // while the operator has granted the community ``restrictions``: without it
  // every member's keys reach it, so there is nothing to set.
  const isSeat = Boolean(activeCommunity?.can.seat);
  const authSettings = useCommunityAuthSettings(activeCommunityId ?? 0, {
    enabled: isSeat && activeCommunityId != null,
  }).data;
  const showsApiAccess = isSeat && (authSettings?.auth_options ?? []).includes("restrictions");
  // Whoever runs the server may set it for the whole community instead.
  const apiAccessFixed = (authSettings?.set_by_deployment ?? []).includes("api_keys");

  const invites = useCommunityInvites(activeCommunityId, managesInvites);
  const [deleteUserConfirm, setDeleteUserConfirm] = useState<{
    userId: number;
    email: string;
  } | null>(null);
  // `member: null` opens the dialog in "claim everything unowned" mode.
  const [namingMember, setNamingMember] = useState<UserCommunityMember | null>(null);
  const [transferTarget, setTransferTarget] = useState<{
    member: UserCommunityMember | null;
  } | null>(null);

  // Searched and paged on the server: the table only ever holds the page on
  // screen.
  const table = useServerTableState();
  const usersQuery = useUsers(table.params, { enabled: opensPage });
  const rows = usersQuery.data?.items ?? [];
  const totalCount = usersQuery.data?.total_count ?? 0;

  // The custom role beside each member, where the community has any; given
  // here by whoever holds the members.
  const customRoles = useCustomRoles({ enabled: opensPage }).data ?? [];
  const customRoleHolders = useCustomRoleHolders({ enabled: customRoles.length > 0 }).data ?? [];
  const heldRoleIds = new Map(customRoleHolders.map((holder) => [holder.user_id, holder.role_id]));
  const assignCustomRole = useAssignCustomRole();
  const customRolesClosed = Boolean(activeCommunity?.closed_surfaces?.includes("custom_roles"));

  const updateCommunityMembership = useUpdateCommunityMembership({
    onError: (error: unknown) => {
      const message = getErrorMessage(error, "communities:users.failedToUpdateRole");
      toast.error(message);
    },
  });

  const setMemberApiAccess = useSetMemberApiAccess({
    onSuccess: () => toast.success(t("users.apiAccessSaved")),
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, "communities:users.apiAccessError"));
    },
  });

  const handleRoleChange = (userId: number, role: CommunityRole) => {
    // Update community membership role
    updateCommunityMembership.mutate({ communityId: activeCommunityId!, userId, role });
  };

  const handleDeleteUser = (userId: number, email: string) => {
    // Backend handles validation (e.g., cannot delete the last platform owner)
    setDeleteUserConfirm({ userId, email });
  };

  const exportCommunityUsers = useExportCommunityUsersCsv({
    onError: (err) => {
      toast.error(getErrorMessage(err, "communities:users.exportError"));
    },
  });

  const exportUserCsv = (communityMember: UserCommunityMember) => {
    const safeHandle = communityMember.username.replace(/[^a-zA-Z0-9._-]+/g, "_");
    exportCommunityUsers.mutate({
      params: { user_id: [communityMember.id] },
      filename: `user-${communityMember.id}-${safeHandle}.csv`,
    });
  };

  const exportAllUsersCsv = () => {
    const safeCommunityName = (activeCommunity?.name ?? "community").replace(
      /[^a-zA-Z0-9._-]+/g,
      "_"
    );
    const datestamp = new Date().toISOString().slice(0, 10);
    exportCommunityUsers.mutate({
      params: {},
      filename: `${safeCommunityName}-users-${datestamp}.csv`,
    });
  };

  if (!opensPage) {
    return <p className="text-muted-foreground text-sm">{t("users.adminRequired")}</p>;
  }

  if (usersQuery.isLoading) {
    return (
      <SkeletonRegion className="space-y-6">
        <FormSkeleton fields={2} />
        <TableSkeleton rows={6} columns={6} />
      </SkeletonRegion>
    );
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <StatusMessage onRetry={usersQuery.refetch} />;
  }

  // The handle leads: every member has one. A name is only the display name
  // somebody set here, so the column shows once someone on the page has one.
  const showsNames = rows.some((row) => row.display_name?.trim());

  const userColumns: AppColumnDef<UserCommunityMember>[] = [
    {
      accessorKey: "id",
      header: t("users.userIdColumn"),
      cell: ({ row }) => (
        <p className="font-mono text-muted-foreground text-sm">{row.original.id}</p>
      ),
    },
    {
      id: "username",
      // The whole handle, as the cell draws it — see the platform roster.
      accessorFn: (row: UserCommunityMember) => getUserHandle(row),
      header: t("users.handleColumn"),
      // The handle is what identifies someone, so it is also what opens them.
      cell: ({ row }) => (
        <Link
          to="/u/$handle"
          params={{ handle: getUrlHandle(row.original) }}
          className="text-sm hover:underline"
        >
          <UserHandle user={row.original} />
        </Link>
      ),
    },
    ...(showsNames
      ? [
          {
            id: "user",
            header: t("users.userColumn"),
            cell: ({ row }) => (
              <div>
                <p className="font-medium">{row.original.display_name?.trim() || "—"}</p>
              </div>
            ),
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
    {
      accessorKey: "community_role",
      header: t("users.communityRoleColumn"),
      cell: ({ row }) => {
        const communityMember = row.original;
        const isSelf = communityMember.id === user?.id;
        const currentCommunityRole = (communityMember.community_role ??
          CommunityRole.member) as CommunityRole;
        if (!managesMembers) {
          return (
            <span className="text-sm">
              {t(`users.communityRole.${currentCommunityRole}` as never)}
            </span>
          );
        }
        // A superadmin's rung answers to the seat.
        const changeable =
          !isSelf && changesRungs && (currentCommunityRole !== CommunityRole.superadmin || isSeat);
        // The rung they hold is listed even where the reader can't give it,
        // so the picker names it.
        const options = roleOptions.includes(currentCommunityRole)
          ? roleOptions
          : [currentCommunityRole, ...roleOptions];
        return (
          <div className="flex flex-col gap-1">
            <Select
              value={currentCommunityRole}
              onValueChange={(value) =>
                handleRoleChange(communityMember.id, value as CommunityRole)
              }
              disabled={!changeable || updateCommunityMembership.isPending}
            >
              <SelectTrigger
                disabled={!changeable}
                className="min-w-40"
                aria-label={t("users.communityRolePickerLabel", {
                  name: getUserDisplayName(communityMember),
                })}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {options.map((roleOption) => (
                  <SelectItem key={roleOption} value={roleOption}>
                    {t(`users.communityRole.${roleOption}` as never)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      },
    },
    ...(customRoles.length > 0
      ? [
          {
            id: "custom_role",
            header: t("settings:customRoles.column"),
            cell: ({ row }) => {
              const communityMember = row.original;
              const roleId = heldRoleIds.get(communityMember.id) ?? null;
              if (!managesMembers) {
                const name = customRoles.find((role) => role.id === roleId)?.name;
                return name ? <span className="text-sm">{name}</span> : null;
              }
              // A role applies while its holder stands on its rung.
              const rung = isAdminRole(communityMember.community_role) ? "admin" : "member";
              // Given only by somebody who could take off the one held now, as
              // on the members page; the held one is listed either way.
              const heldRole = customRoles.find((role) => role.id === roleId);
              const changeable =
                held.writes && !customRolesClosed && (!heldRole || held.takesOff(heldRole));
              const options = customRoles.filter(
                (role) => role.id === roleId || (changeable && held.gives(role))
              );
              return (
                <Select
                  value={roleId === null ? NO_CUSTOM_ROLE : String(roleId)}
                  onValueChange={(value) =>
                    assignCustomRole.mutate({
                      userId: communityMember.id,
                      roleId: value === NO_CUSTOM_ROLE ? null : Number(value),
                    })
                  }
                  disabled={!changeable || assignCustomRole.isPending}
                >
                  <SelectTrigger
                    disabled={!changeable}
                    className="min-w-40"
                    aria-label={t("settings:customRoles.pickerLabel", {
                      name: getUserDisplayName(communityMember),
                    })}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_CUSTOM_ROLE}>{t("settings:customRoles.none")}</SelectItem>
                    {options.map((role) => (
                      <SelectItem key={role.id} value={String(role.id)}>
                        <span className="flex flex-col">
                          <span>{role.name}</span>
                          {role.base_rung === rung ? null : (
                            <span className="text-muted-foreground text-xs">
                              {role.base_rung === "admin"
                                ? t("settings:customRoles.appliesWhileAdmin")
                                : t("settings:customRoles.appliesWhileMember")}
                            </span>
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              );
            },
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
    ...(showsApiAccess
      ? [
          {
            accessorKey: "api_keys_allowed",
            header: t("users.apiAccessColumn"),
            cell: ({ row }) => {
              const communityMember = row.original;
              return (
                <Switch
                  checked={communityMember.api_keys_allowed ?? true}
                  aria-label={t("users.apiAccessLabel", {
                    name: getUserDisplayName(communityMember),
                  })}
                  disabled={setMemberApiAccess.isPending || apiAccessFixed}
                  onCheckedChange={(allowed) =>
                    setMemberApiAccess.mutate({
                      communityId: activeCommunityId!,
                      userId: communityMember.id,
                      allowed,
                    })
                  }
                />
              );
            },
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
    {
      accessorKey: "oidc_managed",
      header: t("users.sourceColumn"),
      cell: ({ row }) => {
        return row.original.oidc_managed ? (
          <span className="inline-flex items-center rounded-md bg-muted px-2 py-1 font-medium text-muted-foreground text-sm">
            {t("users.sourceOidc")}
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">{t("users.sourceManual")}</span>
        );
      },
    },
    ...(managesMembers
      ? [
          {
            id: "actions",
            header: t("users.actionsColumn"),
            cell: ({ row }) => {
              const communityMember = row.original;
              const isSelf = communityMember.id === user?.id;
              return (
                <RowActionsMenu subject={getUserDisplayName(communityMember)}>
                  <DropdownMenuItem onSelect={() => exportUserCsv(communityMember)}>
                    <Download className="h-4 w-4" />
                    {t("users.exportUser")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setNamingMember(communityMember)}>
                    <IdCard className="h-4 w-4" />
                    {t("displayName.adminAction")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setTransferTarget({ member: communityMember })}>
                    <HandCoins className="h-4 w-4" />
                    {t("transferOwnership.action")}
                  </DropdownMenuItem>
                  {/* Removing somebody from the community is the destructive one, and
                the only one you cannot aim at yourself. */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    onSelect={() =>
                      handleDeleteUser(communityMember.id, getUserDisplayName(communityMember))
                    }
                    disabled={isSelf}
                  >
                    <UserMinus className="h-4 w-4" />
                    {t("users.removeFromCommunity")}
                  </DropdownMenuItem>
                </RowActionsMenu>
              );
            },
          } satisfies AppColumnDef<UserCommunityMember>,
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      {managesInvites ? (
        <SettingsSection
          title={t("users.invitesTitle")}
          description={t("users.invitesDescription")}
          action={
            <Button variant="ghost" size="icon" onClick={invites.refresh}>
              <RefreshCcw className="h-4 w-4" />
              <span className="sr-only">{t("users.refreshInvites")}</span>
            </Button>
          }
        >
          <MemberInvites invites={invites} />
        </SettingsSection>
      ) : null}
      <SettingsSection
        // Named only beside the invites card; alone, the tab names it.
        title={managesInvites ? t("users.usersTitle") : undefined}
        description={t("users.usersDescription")}
        action={
          managesMembers ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={exportAllUsersCsv}
              disabled={totalCount === 0 && !table.params.search}
            >
              <Download className="h-4 w-4" />
              {t("users.exportAll")}
            </Button>
          ) : null
        }
      >
        <DataTable
          columns={userColumns}
          data={rows}
          getRowId={(row) => String(row.id)}
          enableFilterInput
          filterInputPlaceholder={t("users.filterByHandle")}
          enablePagination
          {...table.tableProps(totalCount)}
        />
      </SettingsSection>

      {managesMembers ? (
        <UnownedContentCard onClaim={() => setTransferTarget({ member: null })} />
      ) : null}

      <RemoveCommunityMemberDialog
        open={deleteUserConfirm !== null}
        onOpenChange={(open) => !open && setDeleteUserConfirm(null)}
        userId={deleteUserConfirm?.userId ?? null}
        email={deleteUserConfirm?.email ?? ""}
      />

      {activeCommunityId ? (
        <MemberDisplayNameDialog
          open={namingMember !== null}
          onOpenChange={(open) => !open && setNamingMember(null)}
          communityId={activeCommunityId}
          member={
            namingMember ? { id: namingMember.id, name: getUserHandle(namingMember) } : undefined
          }
          current={namingMember?.display_name}
        />
      ) : null}

      <TransferContentOwnershipDialog
        open={transferTarget !== null}
        onOpenChange={(open) => !open && setTransferTarget(null)}
        member={transferTarget?.member ?? null}
        defaultRecipient={user}
        onSuccess={() => void usersQuery.refetch()}
      />
    </div>
  );
};
