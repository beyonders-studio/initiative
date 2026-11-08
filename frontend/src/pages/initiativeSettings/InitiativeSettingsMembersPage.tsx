/**
 * `/settings/members` — how people get into this initiative, the requests
 * waiting to be let in, and who is already here.
 *
 * This is the address the directory's "waiting to join" badge links to, so a
 * manager who notices the count lands on the queue itself.
 *
 * The join policy and the auto-join switch save on change, each sending only
 * the field that moved — with the one coupling the server enforces (auto-join
 * needs an open policy) resolved before the request.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  InitiativeJoinPolicy,
  type InitiativeMemberRead,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsPermissionRequired } from "@/components/initiatives/settings/InitiativeSettingsGuard";
import { InitiativeSettingsMembersTab } from "@/components/initiatives/settings/InitiativeSettingsMembersTab";
import { RemoveInitiativeMemberDialog } from "@/components/initiatives/settings/RemoveInitiativeMemberDialog";
import { useCommunities } from "@/hooks/useCommunities";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiativeSettings } from "@/hooks/useInitiativeSettings";
import { useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/mascotToast";

export const InitiativeSettingsMembersPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeCommunity } = useCommunities();
  const { initiativeId, initiative, canManageMembers, isCommunityAdmin } = useInitiativeSettings();
  const rolesQuery = useInitiativeRoles(initiativeId || null);

  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [memberToRemove, setMemberToRemove] = useState<InitiativeMemberRead | null>(null);

  // The role a new member gets unless the manager picks another.
  useEffect(() => {
    if (rolesQuery.data && !selectedRoleId) {
      const memberRole = rolesQuery.data.find((role) => role.name === "member");
      if (memberRole) {
        setSelectedRoleId(String(memberRole.id));
      }
    }
  }, [rolesQuery.data, selectedRoleId]);

  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
  });

  // Only the field the manager touched is sent, so an unrelated save never
  // rewrites a policy this screen wasn't asked about.
  //
  // The one exception is auto-join, which is not an independent field: it is
  // valid only alongside `open`, so a community admin closing the initiative sends
  // both halves at once rather than being handed a refusal for a pair the UI
  // let them assemble. A manager who is not a community admin cannot send the field
  // at all, so for them the section locks the other policies instead.
  const handleChangeJoinPolicy = (value: InitiativeJoinPolicy) => {
    const clearsAutoJoin =
      isCommunityAdmin && Boolean(initiative?.auto_join) && value !== InitiativeJoinPolicy.open;
    updateInitiative.mutate(
      {
        initiativeId,
        data: clearsAutoJoin ? { join_policy: value, auto_join: false } : { join_policy: value },
      },
      clearsAutoJoin
        ? { onSuccess: () => toast.info(t("initiatives:settings.autoJoin.turnedOff")) }
        : undefined
    );
  };

  const handleChangeAutoJoin = (next: boolean) => {
    updateInitiative.mutate({ initiativeId, data: { auto_join: next } });
  };

  if (!canManageMembers) {
    return <InitiativeSettingsPermissionRequired />;
  }

  if (!initiative) {
    return null;
  }

  return (
    <>
      <InitiativeSettingsMembersTab
        initiativeId={initiativeId}
        roles={rolesQuery.data}
        canManageMembers={canManageMembers}
        joinPolicy={initiative.join_policy}
        onChangeJoinPolicy={handleChangeJoinPolicy}
        autoJoin={initiative.auto_join}
        onChangeAutoJoin={handleChangeAutoJoin}
        canManageAutoJoin={isCommunityAdmin}
        isSavingJoinPolicy={updateInitiative.isPending}
        activeCommunityId={activeCommunity?.id}
        selectedUserId={selectedUserId}
        setSelectedUserId={setSelectedUserId}
        selectedRoleId={selectedRoleId}
        setSelectedRoleId={setSelectedRoleId}
        onRemoveMember={setMemberToRemove}
      />
      <RemoveInitiativeMemberDialog
        initiativeId={initiativeId}
        member={memberToRemove}
        onOpenChange={setMemberToRemove}
      />
    </>
  );
};
