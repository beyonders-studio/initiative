import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeJoinPolicy,
  InitiativeMemberRead,
  InitiativeRoleRead,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { JoinPolicySection } from "@/components/initiatives/JoinPolicySection";
import { InitiativeJoinRequestQueue } from "@/components/initiatives/settings/InitiativeJoinRequestQueue";
import { useSeenMembers } from "@/components/members/MemberSearchSelect";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { UserHandle } from "@/components/UserHandle";
import {
  useAddInitiativeMember,
  useInitiativeRoster,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { useServerTableState } from "@/hooks/useServerTableState";
import {
  type MemberSearchScope,
  USER_ID_LOOKUP_MAX,
  useInitiativeMemberSearch,
  useUserSearch,
} from "@/hooks/useUsers";
import { toast } from "@/lib/mascotToast";
import { isAdminRole } from "@/lib/permissions";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { DataTable } from "@/ui/data-table";
import type { AppColumnDef } from "@/ui/lib/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const COMMUNITY_SCOPE: MemberSearchScope = { type: "community" };
const NONE: never[] = [];

interface InitiativeSettingsMembersTabProps {
  initiativeId: number;
  roles: InitiativeRoleRead[] | undefined;
  canManageMembers: boolean;
  /** How community members may join this initiative. */
  joinPolicy: InitiativeJoinPolicy;
  onChangeJoinPolicy: (value: InitiativeJoinPolicy) => void;
  /** Whether every new community member is enrolled here on arrival. */
  autoJoin: boolean;
  onChangeAutoJoin: (next: boolean) => void;
  /** Auto-join is the community admin's to set, even among initiative managers. */
  canManageAutoJoin: boolean;
  /** A policy or auto-join save is in flight. */
  isSavingJoinPolicy: boolean;
  activeCommunityId: number | undefined;
  selectedUserId: string;
  setSelectedUserId: (value: string) => void;
  selectedRoleId: string;
  setSelectedRoleId: (value: string) => void;
  onRemoveMember: (member: InitiativeMemberRead) => void;
}

export const InitiativeSettingsMembersTab = ({
  initiativeId,
  roles,
  canManageMembers,
  joinPolicy,
  onChangeJoinPolicy,
  autoJoin,
  onChangeAutoJoin,
  canManageAutoJoin,
  isSavingJoinPolicy,
  activeCommunityId,
  selectedUserId,
  setSelectedUserId,
  selectedRoleId,
  setSelectedRoleId,
  onRemoveMember,
}: InitiativeSettingsMembersTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  // The roster is searched and paged on the server: the table only ever holds
  // the page on screen.
  const table = useServerTableState();
  const rosterQuery = useInitiativeRoster(initiativeId, table.params);
  const members = useMemo(() => rosterQuery.data?.items ?? [], [rosterQuery.data]);
  const totalCount = rosterQuery.data?.total_count ?? 0;

  // The add-member picker asks the community for the people matching what was
  // typed, once it is open, and leaves out the ones already here. Only a
  // members manager is shown it.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const candidatesQuery = useUserSearch({
    search,
    enabled: canManageMembers && !!activeCommunityId && pickerOpen,
  });
  const candidateIds = useMemo(
    () => (candidatesQuery.data?.items ?? []).map((candidate) => candidate.id),
    [candidatesQuery.data]
  );
  const alreadyInQuery = useInitiativeMemberSearch(initiativeId, {
    userIds: candidateIds,
    pageSize: USER_ID_LOOKUP_MAX,
    enabled: candidateIds.length > 0,
  });
  const availableUsers = useMemo(() => {
    const existingIds = new Set((alreadyInQuery.data?.items ?? []).map((member) => member.id));
    return (candidatesQuery.data?.items ?? []).filter(
      (candidate) => !existingIds.has(candidate.id) && candidate.status !== "anonymized"
    );
  }, [candidatesQuery.data, alreadyInQuery.data]);
  const memberIds = useMemo(() => members.map((member) => member.user.id), [members]);
  // The person picked, held so the trigger keeps their name (and the role
  // select their standing) after the search moves on.
  const [picked, setPicked] = useState<UserSummary | null>(null);
  const pickedUser = picked && String(picked.id) === selectedUserId ? picked : null;

  // A community admin's standing already reaches every initiative, so their row
  // lands on the moderator role — the server settles that on the way in. The
  // picker says so up front rather than offering a choice that would be
  // rewritten. Who is an admin is the community's to say, so the members already
  // here are looked up by id.
  const knownMembers = useSeenMembers(
    COMMUNITY_SCOPE,
    canManageMembers ? memberIds : NONE,
    undefined,
    NONE
  );
  const adminIds = useMemo(
    () =>
      new Set(
        [...knownMembers.values()]
          .filter((member) => isAdminRole(member.community_role))
          .map((member) => member.id)
      ),
    [knownMembers]
  );
  const adminRole = useMemo(
    () =>
      roles?.find((role) => role.name === "moderator") ?? roles?.find((role) => role.is_manager),
    [roles]
  );
  const addingAdmin = isAdminRole(pickedUser?.community_role);
  const effectiveRoleId = addingAdmin && adminRole ? String(adminRole.id) : selectedRoleId;

  const addMember = useAddInitiativeMember(
    {
      onSuccess: () => {
        toast.success(t("settings.memberAdded"));
        setSelectedUserId("");
      },
    },
    "initiatives:settings.addMemberError"
  );

  const removeMember = useRemoveInitiativeMember(
    { onSuccess: () => toast.success(t("settings.memberRemoved")) },
    "initiatives:settings.removeMemberError"
  );

  const updateMemberRole = useUpdateInitiativeMember(
    { onSuccess: () => toast.success(t("settings.roleUpdated")) },
    "initiatives:settings.roleUpdateError"
  );

  const handleAddMember = () => {
    if (!selectedUserId || !effectiveRoleId) {
      return;
    }
    const userId = Number(selectedUserId);
    const roleId = Number(effectiveRoleId);
    if (!Number.isFinite(userId) || !Number.isFinite(roleId)) {
      return;
    }
    addMember.mutate({ initiativeId, data: { user_id: userId, role_id: roleId } });
  };

  // A name is only the display name somebody set in this community, so the
  // name column shows once someone here has one.
  const showsNames = members.some((member) => member.user.display_name?.trim());

  const memberColumns: AppColumnDef<InitiativeMemberRead>[] = useMemo(() => {
    const getRoleDisplayName = (member: InitiativeMemberRead): string => {
      if (member.role_display_name) {
        return member.role_display_name;
      }
      const roleFromList = roles?.find((role) => role.name === member.role_name)?.display_name;
      return roleFromList ?? member.role_name ?? "";
    };

    return [
      // The handle leads: every community has one for every member, and it is the
      // identifier the rest of the app shows.
      {
        id: "handle",
        accessorKey: "user.username",
        header: t("settings.handleColumn"),
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-2">
            <UserHandle user={row.original.user} />
            {row.original.guest_until ? (
              <Badge variant="secondary">{t("detail.guest")}</Badge>
            ) : null}
          </span>
        ),
      },
      // Without a display name on the page this column would be a full one of
      // em-dashes.
      ...(showsNames
        ? [
            {
              id: "name",
              accessorKey: "user.display_name",
              header: t("settings.nameColumn"),
              cell: ({ row }) => (
                <span className="font-medium">{row.original.user.display_name?.trim() || "—"}</span>
              ),
            } satisfies AppColumnDef<InitiativeMemberRead>,
          ]
        : []),
      {
        accessorKey: "role_name",
        header: t("settings.roleColumn"),
        cell: ({ row }) => {
          const member = row.original;
          if (!canManageMembers || !roles) {
            return <Badge variant="outline">{getRoleDisplayName(member)}</Badge>;
          }
          // A community admin already on a manager role has nothing to choose:
          // it is the only role their row can hold. One that is not — promoted
          // to admin after joining, so their row kept the role they joined
          // with — keeps the picker, narrowed to the manager roles, because
          // this is where that row gets put right.
          const isAdmin = adminIds.has(member.user.id);
          if (isAdmin && member.is_manager) {
            return <Badge variant="outline">{getRoleDisplayName(member)}</Badge>;
          }
          const options = isAdmin ? roles.filter((role) => role.is_manager) : roles;
          return (
            <Select
              value={String(member.role_id || "")}
              onValueChange={(value) =>
                updateMemberRole.mutate({
                  initiativeId,
                  userId: member.user.id,
                  data: { role_id: Number(value) },
                })
              }
              disabled={updateMemberRole.isPending}
            >
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Role" />
              </SelectTrigger>
              <SelectContent>
                {options.map((role) => (
                  <SelectItem key={role.id} value={String(role.id)}>
                    {role.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          );
        },
      },
      {
        accessorKey: "oidc_managed",
        header: t("settings.sourceColumn"),
        cell: ({ row }) => {
          return row.original.oidc_managed ? (
            <span className="inline-flex items-center rounded-md bg-muted px-2 py-1 font-medium text-muted-foreground text-sm">
              {t("settings.sourceOidc")}
            </span>
          ) : (
            <span className="text-muted-foreground text-sm">{t("settings.sourceManual")}</span>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const member = row.original;
          if (!canManageMembers) {
            return null;
          }
          return (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemoveMember(member)}
              disabled={removeMember.isPending}
              className="text-destructive"
            >
              {t("settings.removeMember")}
            </Button>
          );
        },
      },
    ];
  }, [
    t,
    adminIds,
    canManageMembers,
    roles,
    showsNames,
    removeMember,
    updateMemberRole,
    initiativeId,
    onRemoveMember,
  ]);

  return (
    <div className="space-y-6">
      {/* Requests come before the roster: they are the roster's inbox, and
          answering one is the same act as adding a member by hand. Manager-only,
          matching who may answer them. */}
      {canManageMembers ? <InitiativeJoinRequestQueue initiativeId={initiativeId} /> : null}
      {/* The door, above the people who came through it. It saves on change —
          it is a single setting, not a field of a form with a Save button. */}
      <JoinPolicySection
        value={joinPolicy}
        onChange={onChangeJoinPolicy}
        canManage={canManageMembers}
        isSaving={isSavingJoinPolicy}
        autoJoin={autoJoin}
        // Absent for a manager who is not a community admin: the server refuses the
        // field from them, so the control is not offered rather than shown inert.
        onChangeAutoJoin={canManageAutoJoin ? onChangeAutoJoin : undefined}
      />
      <SettingsSection
        title={t("settings.membersTitle")}
        description={t("settings.membersDescription")}
      >
        <DataTable
          columns={memberColumns}
          data={members}
          getRowId={(row) => String(row.user.id)}
          enableFilterInput
          filterInputPlaceholder={t("settings.filterByName")}
          enablePagination
          // The page the server answered with: a page emptied by a removal
          // comes back as page 1.
          {...table.tableProps(totalCount, rosterQuery.data?.page)}
        />
        {canManageMembers ? (
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <Combobox
                items={availableUsers.map((candidate) => ({
                  value: String(candidate.id),
                  label: getUserDisplayName(candidate),
                }))}
                value={selectedUserId}
                onValueChange={(value) => {
                  setPicked(availableUsers.find((c) => String(c.id) === value) ?? null);
                  setSelectedUserId(value);
                }}
                onSearchChange={setSearch}
                onOpenChange={setPickerOpen}
                selectedLabel={pickedUser ? getUserDisplayName(pickedUser) : null}
                loading={candidatesQuery.isFetching && availableUsers.length === 0}
                placeholder={t("settings.selectUser")}
                emptyMessage={t("settings.noOneToAdd")}
                aria-label={t("settings.selectUser")}
              />
              {roles && (
                <Select
                  value={effectiveRoleId}
                  onValueChange={setSelectedRoleId}
                  disabled={addingAdmin}
                >
                  <SelectTrigger className="w-44">
                    <SelectValue placeholder={t("settings.selectRole")} />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((role) => (
                      <SelectItem key={role.id} value={String(role.id)}>
                        {role.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Button
                type="button"
                variant="outline"
                onClick={handleAddMember}
                disabled={!selectedUserId || !effectiveRoleId}
                pending={addMember.isPending}
              >
                {addMember.isPending ? t("settings.adding") : t("settings.addMember")}
              </Button>
            </div>
            {candidatesQuery.isError ? (
              <p className="text-destructive text-xs">{t("settings.unableToLoadMembers")}</p>
            ) : null}
          </>
        ) : null}
      </SettingsSection>
    </div>
  );
};
