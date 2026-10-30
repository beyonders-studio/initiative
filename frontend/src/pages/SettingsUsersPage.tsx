import { Link } from "@tanstack/react-router";
import { Download, HandCoins, IdCard, RefreshCcw, UserMinus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CommunityRole,
  SupportTopic,
  type UserCommunityMember,
} from "@/api/generated/initiativeAPI.schemas";
import {
  CommunityInviteList,
  InviteLimitFields,
  NewInviteLink,
} from "@/components/communities/CommunityInvites";
import { MemberDisplayNameDialog } from "@/components/communities/MemberDisplayNameDialog";
import { RemoveCommunityMemberDialog } from "@/components/communities/RemoveCommunityMemberDialog";
import { TransferContentOwnershipDialog } from "@/components/communities/TransferContentOwnershipDialog";
import { UnownedContentCard } from "@/components/communities/UnownedContentCard";
import { FormSkeleton, SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { HelpLink } from "@/components/support/HelpLink";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { RowActionsMenu } from "@/components/ui/row-actions-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useBillingPortal } from "@/hooks/useBillingPortal";
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
import { isAdminRole } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUrlHandle, getUserDisplayName, getUserHandle } from "@/lib/userDisplay";

//: What this community's roles are, in the order the picker offers them. The
//: seat is only on the list for somebody who already holds it — an admin can
//: neither appoint nor demote one, and the server says so too.
const COMMUNITY_ROLE_OPTIONS: CommunityRole[] = ["admin", "member"];
const SEAT_ROLE_OPTIONS: CommunityRole[] = ["superadmin", "admin", "member"];
//: The custom role picker's "none", since a select's value is a string.
const NO_CUSTOM_ROLE = "none";

export const SettingsUsersPage = () => {
  const { user } = useAuth();
  const { t } = useTranslation(["communities", "settings"]);

  const { activeCommunity } = useCommunities();
  const { canSell, openPortal } = useBillingPortal();
  // Running the community, not reaching its work: the roster and its
  // invites are parts of running it, held by its admins, by a custom role, or
  // by a settings grant standing in. Platform role has nothing to do with it.
  const held = useHeldSurfaces();
  const managesMembers = held.holds("members");
  // Invites are handed out by whoever holds them and may change what they
  // hold, so a grant that only reads does not list them.
  const managesInvites = held.writes && held.holds("invites");
  const opensPage = managesMembers || held.holds("invites");
  const roleOptions = activeCommunity?.can.seat ? SEAT_ROLE_OPTIONS : COMMUNITY_ROLE_OPTIONS;

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

  // Seat cap, admin-only on the payload and null when uncapped. A full community
  // mints no invite (the server refuses), so the form says so up front instead
  // of failing on submit. Where a billing portal exists the cap travels with
  // the plan — raising it is an upgrade, not a request to an operator — so the
  // message and its action differ from the self-hosted one.
  const maxUsers = activeCommunity?.max_users ?? null;
  const usedSeats = activeCommunity?.member_count ?? 0;
  const atUserLimit = maxUsers !== null && usedSeats >= maxUsers;
  const planName = activeCommunity?.tier_name ?? null;

  const invites = useCommunityInvites(activeCommunityId, managesInvites);
  // Guest invites are Settings › Guests'; these are for members.
  const memberInvites = invites.invites.filter((invite) => invite.guest_days == null);
  const [inviteLimits, setInviteLimits] = useState({ maxUses: 1, expiresDays: 7 });
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
      <SkeletonRegion label={t("users.loadingSettings")} className="space-y-6">
        <FormSkeleton fields={2} />
        <TableSkeleton rows={6} columns={6} />
      </SkeletonRegion>
    );
  }

  if (usersQuery.isError || !usersQuery.data) {
    return <p className="text-destructive text-sm">{t("users.unableToLoadSettings")}</p>;
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
        const currentCommunityRole = communityMember.community_role ?? "member";
        if (!managesMembers) {
          return (
            <span className="text-sm">
              {t(`users.communityRole.${currentCommunityRole}` as never)}
            </span>
          );
        }
        return (
          <div className="flex flex-col gap-1">
            <Select
              value={currentCommunityRole}
              onValueChange={(value) =>
                handleRoleChange(communityMember.id, value as CommunityRole)
              }
              disabled={isSelf || updateCommunityMembership.isPending}
            >
              <SelectTrigger disabled={isSelf} className="min-w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roleOptions.map((roleOption) => (
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
              if (!managesMembers || customRolesClosed) {
                const name = customRoles.find((role) => role.id === roleId)?.name;
                return name ? <span className="text-sm">{name}</span> : null;
              }
              // A role applies while its holder stands on its rung.
              const rung = isAdminRole(communityMember.community_role) ? "admin" : "member";
              return (
                <Select
                  value={roleId === null ? NO_CUSTOM_ROLE : String(roleId)}
                  onValueChange={(value) =>
                    assignCustomRole.mutate({
                      userId: communityMember.id,
                      roleId: value === NO_CUSTOM_ROLE ? null : Number(value),
                    })
                  }
                  disabled={assignCustomRole.isPending}
                >
                  <SelectTrigger
                    className="min-w-40"
                    aria-label={t("settings:customRoles.pickerLabel", {
                      name: getUserDisplayName(communityMember),
                    })}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_CUSTOM_ROLE}>{t("settings:customRoles.none")}</SelectItem>
                    {customRoles.map((role) => (
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

  const createInvite = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!atUserLimit) void invites.create(inviteLimits);
  };

  return (
    <div className="space-y-6">
      {managesInvites ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>{t("users.invitesTitle")}</CardTitle>
              <p className="text-muted-foreground text-sm">{t("users.invitesDescription")}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={invites.refresh}>
              <RefreshCcw className="h-4 w-4" />
              <span className="sr-only">{t("users.refreshInvites")}</span>
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="grid grid-cols-fill-48/3 gap-4" onSubmit={createInvite}>
              <InviteLimitFields
                idPrefix="invite"
                value={inviteLimits}
                onChange={setInviteLimits}
              />
              <div className="flex items-end">
                <Button type="submit" disabled={invites.submitting || atUserLimit}>
                  {invites.submitting ? t("users.generatingInvite") : t("users.generateInvite")}
                </Button>
              </div>
            </form>
            {atUserLimit && canSell && activeCommunityId && activeCommunity?.can.seat ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-muted-foreground text-sm">
                  {planName
                    ? t("users.inviteSeatsFullPlan", { plan: planName, count: maxUsers ?? 0 })
                    : t("users.inviteSeatsFullUpgrade", { count: maxUsers ?? 0 })}
                </p>
                <Button size="sm" onClick={() => void openPortal(activeCommunityId, "upgrade")}>
                  {t("usagePanel.upgrade")}
                </Button>
              </div>
            ) : atUserLimit ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <p className="text-muted-foreground text-sm">
                  {t("users.inviteSeatsFull", { max: maxUsers })}
                </p>
                <HelpLink topic={SupportTopic.community} communityId={activeCommunityId} />
              </div>
            ) : null}
            {invites.newInviteCode ? <NewInviteLink code={invites.newInviteCode} /> : null}
            <div className="h-px bg-border" />
            <CommunityInviteList
              invites={memberInvites}
              isLoading={invites.isLoading}
              error={invites.error}
              emptyText={t("users.noActiveInvites")}
              onDelete={(inviteId) => void invites.remove(inviteId)}
            />
          </CardContent>
        </Card>
      ) : null}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            {/* Named only beside the invites card; alone, the tab names it. */}
            {managesInvites ? <CardTitle>{t("users.usersTitle")}</CardTitle> : null}
            <CardDescription>{t("users.usersDescription")}</CardDescription>
            {/* Three words that get mixed up constantly, explained where the
                choice is actually made rather than in the help centre. */}
            <dl className="mt-3 space-y-1 text-muted-foreground text-xs">
              {roleOptions.map((roleOption) => (
                <div key={roleOption} className="flex gap-1.5">
                  <dt className="font-medium text-foreground">
                    {t(`users.communityRole.${roleOption}` as never)}
                  </dt>
                  <dd>{t(`users.communityRoleHelp.${roleOption}` as never)}</dd>
                </div>
              ))}
              {showsApiAccess ? (
                <div className="flex gap-1.5">
                  <dt className="font-medium text-foreground">{t("users.apiAccessColumn")}</dt>
                  <dd>
                    {apiAccessFixed
                      ? t("settings:communityAuth.setByDeployment")
                      : t("users.apiAccessHelp")}
                  </dd>
                </div>
              ) : null}
            </dl>
          </div>
          {managesMembers ? (
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
          ) : null}
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={userColumns}
            data={rows}
            getRowId={(row) => String(row.id)}
            enableFilterInput
            filterInputPlaceholder={t("users.filterByHandle")}
            enablePagination
            {...table.tableProps(totalCount)}
          />
        </CardContent>
      </Card>

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
