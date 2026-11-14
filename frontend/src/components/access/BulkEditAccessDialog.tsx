import { useQueries } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ResourceGrantBulkItem,
  ResourceGrantSchema,
  SearchInitiativeMembersParams,
  Tool,
  ToolCan,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListInitiativeRolesQueryOptions,
  getSearchInitiativeMembersQueryOptions,
} from "@/api/generated/initiatives/initiatives";
import { bulkSetResourceGrants } from "@/api/generated/resource-grants/resource-grants";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useAuth } from "@/hooks/useAuth";
import { useInitiatives } from "@/hooks/useInitiatives";
import { USER_ID_LOOKUP_MAX, USER_SEARCH_PAGE_SIZE } from "@/hooks/useUsers";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import type { DialogWithSuccessProps } from "@/types/dialog";
import { Combobox, type ComboboxItem } from "@/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/ui/tabs";

/** The minimal shape the bulk dialog needs from any tool (project, file, …). */
export interface BulkAccessItem {
  id: number;
  initiative_id: number | null;
  archived_at?: string | null;
  /** A template, which anyone who reads it may copy. */
  is_template?: boolean;
  grants?: ResourceGrantSchema[] | null;
  can: ToolCan;
}

interface BulkEditAccessDialogProps extends DialogWithSuccessProps {
  /** The selected resources to edit sharing on. */
  items: BulkAccessItem[];
  /** Which tool these are — routes to the right adapter server-side. */
  resourceType: Tool;
  /** Invalidate the relevant list caches after a successful change. */
  invalidate: () => void;
}

interface SelectableRole {
  id: number;
  name: string;
  displayName: string;
  initiativeId: number;
  initiativeName: string;
}

// The bulk endpoint caps items per request; chunk larger selections transparently.
const MAX_BULK_ITEMS = 200;

type MemberSearchParams = SearchInitiativeMembersParams;

/** A member as a row of the people picker. The handle goes under the name,
 *  which is what tells two of the same name apart. */
const toPersonItem = (member: UserSummary): ComboboxItem => {
  const label = getUserDisplayName(member);
  const handle = getUserHandle(member);
  return { value: String(member.id), label, sublabel: handle === label ? undefined : handle };
};

/**
 * Bulk-edit sharing across many resources of one tool type. Keeps a safe
 * additive add/remove model (People / Roles) plus an All-members mode, and
 * persists every change in one bulk request per chunk. Resource-agnostic — the
 * per-tool wrappers (files, projects, counters) supply `items`,
 * `resourceType`, and how to invalidate their caches.
 */
export function BulkEditAccessDialog({
  open,
  onOpenChange,
  items,
  resourceType,
  invalidate,
  onSuccess,
}: BulkEditAccessDialogProps) {
  const { t } = useTranslation(["access", "common"]);
  const communityId = useActiveCommunityId();
  const { user: currentUser } = useAuth();
  // The tool noun, pluralized for `count`, so descriptions/toasts read "2 projects"
  // rather than a hardcoded "files".
  const resourceNoun = useCallback(
    (n: number) => t(`bulkBar.resource_${resourceType}`, { count: n }),
    [t, resourceType]
  );
  const [tab, setTab] = useState<"people" | "roles" | "all">("people");

  // Individual people state
  const [userMode, setUserMode] = useState<"grant" | "revoke">("grant");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [level, setLevel] = useState<"read" | "write">("read");
  const [userSearch, setUserSearch] = useState("");

  // Role state
  const [roleMode, setRoleMode] = useState<"grant" | "revoke">("grant");
  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());
  const [roleLevel, setRoleLevel] = useState<"read" | "write">("read");

  // All-initiative-members state (the "all members" share mode, applied in bulk)
  const [allMode, setAllMode] = useState<"share" | "remove">("share");
  const [allLevel, setAllLevel] = useState<"read" | "write">("read");

  // Gather unique initiative IDs from the selected resources
  const initiativeIds = useMemo(() => {
    const ids = new Set<number>();
    for (const item of items) {
      if (item.initiative_id) ids.add(item.initiative_id);
    }
    return [...ids];
  }, [items]);

  // Fetch initiative names
  const { data: initiatives = [] } = useInitiatives({ enabled: open });

  const initiativeNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const initiative of initiatives) map.set(initiative.id, initiative.name);
    return map;
  }, [initiatives]);

  // One query per initiative and params: the people matching what was typed
  // (grant), or the people already granted, named by id (revoke).
  const memberQuery = (initiativeId: number, params: MemberSearchParams, enabled: boolean) =>
    getSearchInitiativeMembersQueryOptions(communityId, initiativeId, params, {
      query: { enabled },
    });

  // Granting: each relevant initiative's members matching what was typed,
  // matched on the server.
  const searchQueries = useQueries({
    queries: initiativeIds.map((id) =>
      memberQuery(
        id,
        { search: userSearch.trim() || undefined, page_size: USER_SEARCH_PAGE_SIZE },
        open && userMode === "grant"
      )
    ),
  });

  // Revoking: the people granted on the selected resources, looked up by id in
  // their resource's initiative a lookup page at a time.
  const granteeLookups = useMemo(() => {
    const byInitiative = new Map<number, Set<number>>();
    for (const item of items) {
      for (const grant of item.grants ?? []) {
        if (!item.initiative_id || grant.user_id == null || grant.level === "owner") continue;
        const ids = byInitiative.get(item.initiative_id) ?? new Set<number>();
        ids.add(grant.user_id);
        byInitiative.set(item.initiative_id, ids);
      }
    }
    return [...byInitiative].flatMap(([initiativeId, ids]) => {
      const sorted = [...ids].sort((a, b) => a - b);
      const pages = [];
      for (let i = 0; i < sorted.length; i += USER_ID_LOOKUP_MAX) {
        pages.push({ initiativeId, userIds: sorted.slice(i, i + USER_ID_LOOKUP_MAX) });
      }
      return pages;
    });
  }, [items]);
  const granteeQueries = useQueries({
    queries: granteeLookups.map(({ initiativeId, userIds }) =>
      memberQuery(
        initiativeId,
        { user_id: userIds, page_size: USER_ID_LOOKUP_MAX },
        open && userMode === "revoke"
      )
    ),
  });

  const membersById = useMemo(() => {
    const map = new Map<number, ComboboxItem>();
    for (const query of granteeQueries) {
      for (const member of query.data?.items ?? []) {
        if (!map.has(member.id)) map.set(member.id, toPersonItem(member));
      }
    }
    return map;
  }, [granteeQueries]);

  // Fetch roles for each relevant initiative (reuses same query key as useInitiativeRoles)
  const roleQueries = useQueries({
    queries: initiativeIds.map((id) =>
      getListInitiativeRolesQueryOptions(communityId, id, { query: { enabled: open } })
    ),
  });

  // Build selectable roles from all relevant initiatives
  const availableRoles = useMemo(() => {
    const roles: SelectableRole[] = [];
    for (let i = 0; i < roleQueries.length; i++) {
      const query = roleQueries[i];
      const initiativeId = initiativeIds[i];
      if (!query.data) continue;
      for (const role of query.data) {
        roles.push({
          id: role.id,
          name: role.name,
          displayName: role.display_name,
          initiativeId,
          initiativeName: initiativeNameById.get(initiativeId) ?? `Initiative ${initiativeId}`,
        });
      }
    }
    return roles.sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [roleQueries, initiativeIds, initiativeNameById]);

  // Resolve a role id to its display info (from the fetched initiative roles).
  const rolesById = useMemo(() => {
    const map = new Map<number, SelectableRole>();
    for (const role of availableRoles) map.set(role.id, role);
    return map;
  }, [availableRoles]);

  // Roles that are currently granted on at least one selected resource (for revoke)
  const revocableRoles = useMemo(() => {
    const roleMap = new Map<number, SelectableRole>();
    for (const item of items) {
      // Roles are an initiative's; a community-level row carries none.
      const initiativeId = item.initiative_id;
      if (initiativeId === null) continue;
      for (const grant of item.grants ?? []) {
        if (grant.role_id == null || roleMap.has(grant.role_id)) continue;
        const known = rolesById.get(grant.role_id);
        roleMap.set(grant.role_id, {
          id: grant.role_id,
          name: known?.name ?? `role-${grant.role_id}`,
          displayName: known?.displayName ?? `Role ${grant.role_id}`,
          initiativeId,
          initiativeName: initiativeNameById.get(initiativeId) ?? `Initiative ${initiativeId}`,
        });
      }
    }
    return Array.from(roleMap.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [items, rolesById, initiativeNameById]);

  const displayRoles = roleMode === "grant" ? availableRoles : revocableRoles;

  // People from the initiatives the selected resources belong to
  const availableUsers = useMemo(() => {
    const map = new Map<number, ComboboxItem>();
    for (const query of searchQueries) {
      for (const member of query.data?.items ?? []) {
        if (member.id !== currentUser?.id && !map.has(member.id)) {
          map.set(member.id, toPersonItem(member));
        }
      }
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [searchQueries, currentUser]);

  // People who have non-owner access on at least one selected resource (for revoke)
  const revocableUsers = useMemo(() => {
    const userMap = new Map<number, ComboboxItem>();
    for (const item of items) {
      for (const grant of item.grants ?? []) {
        const userId = grant.user_id;
        if (
          userId != null &&
          grant.level !== "owner" &&
          userId !== currentUser?.id &&
          !userMap.has(userId)
        ) {
          userMap.set(
            userId,
            membersById.get(userId) ?? { value: String(userId), label: `User ${userId}` }
          );
        }
      }
    }
    return Array.from(userMap.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [items, membersById, currentUser]);

  const resetState = useCallback(() => {
    setTab("people");
    setUserMode("grant");
    setSelectedUserIds(new Set());
    setLevel("read");
    setUserSearch("");
    setRoleMode("grant");
    setSelectedRoleIds(new Set());
    setRoleLevel("read");
    setAllMode("share");
    setAllLevel("read");
  }, []);

  const handleOpenChange = useCallback(
    (value: boolean) => {
      if (!value) {
        resetState();
      }
      onOpenChange(value);
    },
    [onOpenChange, resetState]
  );

  // Persist rebuilt grant lists in one bulk request per chunk (owner preserved
  // server-side). Each entry is one resource's full non-owner grant list.
  const { mutate: applyBulk, isPending } = useCommunityMutation({
    mutationFn: async (
      communityId,
      entries: { resourceId: number; grants: ResourceGrantSchema[] }[]
    ) => {
      for (let i = 0; i < entries.length; i += MAX_BULK_ITEMS) {
        const slice = entries.slice(i, i + MAX_BULK_ITEMS);
        const bulkItems: ResourceGrantBulkItem[] = slice.map((e) => ({
          resource_type: resourceType,
          resource_id: e.resourceId,
          grants: e.grants,
        }));
        await bulkSetResourceGrants(communityId, {
          items: bulkItems,
        });
      }
    },
    // Here rather than in a call's callbacks, which do not run once the dialog
    // is gone, so the lists refresh even when the page is left mid-write.
    invalidate,
  });

  const finish = useCallback(() => {
    resetState();
    onOpenChange(false);
    onSuccess();
  }, [resetState, onOpenChange, onSuccess]);

  const handleApply = useCallback(() => {
    if (selectedUserIds.size === 0) return;

    const userIds = new Set(selectedUserIds);
    const entries: { resourceId: number; grants: ResourceGrantSchema[] }[] = [];

    for (const item of items) {
      const existing = (item.grants ?? []).filter((g) => g.level !== "owner");
      if (userMode === "grant") {
        // Granting specific people switches the resource to "restricted" mode,
        // so drop any "all initiative members" grant — ShareControl can't
        // represent a mixed all-members + per-grantee list and would silently
        // discard it on the next save. Also drop any existing per-user grant for
        // the targeted people, then add them back at the chosen level.
        const next = existing.filter(
          (g) => !g.all_initiative_members && (g.user_id == null || !userIds.has(g.user_id))
        );
        for (const userId of userIds) next.push({ user_id: userId, level });
        entries.push({ resourceId: item.id, grants: next });
      } else {
        // Revoke: only touch items that actually grant one of the targeted
        // people, so the count/toast reflect real changes (not every selection).
        const hasTarget = existing.some((g) => g.user_id != null && userIds.has(g.user_id));
        if (!hasTarget) continue;
        entries.push({
          resourceId: item.id,
          grants: existing.filter((g) => g.user_id == null || !userIds.has(g.user_id)),
        });
      }
    }

    applyBulk(entries, {
      onSuccess: () => {
        const affected = entries.length;
        if (userMode === "grant") {
          toast.success(
            t("bulkAccess.userAccessGranted", { count: affected, items: resourceNoun(affected) })
          );
        } else if (affected === 0) {
          toast.info(t("bulkAccess.nothingToUpdate"));
        } else {
          toast.success(
            t("bulkAccess.userAccessRevoked", { count: affected, items: resourceNoun(affected) })
          );
        }
        finish();
      },
      onError: (error) => toast.error(getErrorMessage(error, "access:bulkAccess.updateError")),
    });
  }, [selectedUserIds, userMode, items, level, applyBulk, finish, resourceNoun, t]);

  const handleApplyRoles = useCallback(() => {
    if (selectedRoleIds.size === 0) return;

    const roleIds = [...selectedRoleIds];
    const entries: { resourceId: number; grants: ResourceGrantSchema[] }[] = [];

    for (const item of items) {
      const existing = (item.grants ?? []).filter((g) => g.level !== "owner");
      const grantedRoleIds = new Set(
        existing.filter((g) => g.role_id != null).map((g) => g.role_id as number)
      );

      if (roleMode === "grant") {
        // Only grant roles that belong to this item's initiative and aren't already granted.
        const itemRoleIds = availableRoles
          .filter((r) => r.initiativeId === item.initiative_id && roleIds.includes(r.id))
          .map((r) => r.id)
          .filter((id) => !grantedRoleIds.has(id));
        if (itemRoleIds.length === 0) continue;
        entries.push({
          resourceId: item.id,
          grants: [
            // Granting specific roles switches the resource to "restricted" mode;
            // drop any "all initiative members" grant so ShareControl doesn't
            // receive a mixed list it can't display.
            ...existing.filter((g) => !g.all_initiative_members),
            ...itemRoleIds.map((id) => ({ role_id: id, level: roleLevel })),
          ],
        });
      } else {
        const toRevoke = roleIds.filter((id) => grantedRoleIds.has(id));
        if (toRevoke.length === 0) continue;
        const revokeSet = new Set(toRevoke);
        entries.push({
          resourceId: item.id,
          grants: existing.filter((g) => g.role_id == null || !revokeSet.has(g.role_id)),
        });
      }
    }

    applyBulk(entries, {
      onSuccess: () => {
        const affected = entries.length;
        if (affected === 0) {
          toast.info(t("bulkAccess.rolesAlreadyAssigned"));
        } else {
          toast.success(
            roleMode === "grant"
              ? t("bulkAccess.roleAccessGranted", {
                  count: affected,
                  items: resourceNoun(affected),
                })
              : t("bulkAccess.roleAccessRevoked", {
                  count: affected,
                  items: resourceNoun(affected),
                })
          );
        }
        finish();
      },
      onError: (error) => toast.error(getErrorMessage(error, "access:bulkAccess.roleUpdateError")),
    });
  }, [
    selectedRoleIds,
    roleMode,
    roleLevel,
    items,
    availableRoles,
    applyBulk,
    finish,
    resourceNoun,
    t,
  ]);

  const handleApplyAllMembers = useCallback(() => {
    const onError = (error: Error) =>
      toast.error(getErrorMessage(error, "access:bulkAccess.updateError"));
    if (allMode === "share") {
      // Switch every selected resource to "all members" mode: a single
      // all-members grant. Per-person and per-role grants are dropped so the
      // resource has one coherent share mode. The owner is preserved
      // server-side, so we don't send it.
      applyBulk(
        items.map((item) => ({
          resourceId: item.id,
          grants: [{ all_initiative_members: true, level: allLevel }],
        })),
        {
          onSuccess: () => {
            toast.success(
              t("bulkAccess.allMembersShared", {
                count: items.length,
                items: resourceNoun(items.length),
              })
            );
            finish();
          },
          onError,
        }
      );
      return;
    }
    // Only touch resources that actually have an all-members grant — an
    // unchanged write is pointless and would let the toast claim removals
    // that never happened.
    const affected = items.filter((item) =>
      (item.grants ?? []).some((g) => g.all_initiative_members)
    );
    applyBulk(
      affected.map((item) => ({
        resourceId: item.id,
        grants: (item.grants ?? []).filter((g) => g.level !== "owner" && !g.all_initiative_members),
      })),
      {
        onSuccess: () => {
          if (affected.length === 0) {
            toast.info(t("bulkAccess.noAllMembersAccess"));
          } else {
            toast.success(
              t("bulkAccess.allMembersRemoved", {
                count: affected.length,
                items: resourceNoun(affected.length),
              })
            );
          }
          finish();
        },
        onError,
      }
    );
  }, [allMode, allLevel, items, applyBulk, finish, resourceNoun, t]);

  const selectedUserCount = selectedUserIds.size;
  const selectedRoleCount = selectedRoleIds.size;
  const canApplyUsers = selectedUserCount > 0;
  const canApplyRoles = selectedRoleCount > 0;

  const count = items.length;
  const dialogDescription = useMemo(() => {
    const opts = { count, items: resourceNoun(count) };
    if (tab === "roles") {
      return roleMode === "grant"
        ? t("bulkAccess.descriptionGrant", opts)
        : t("bulkAccess.descriptionRevoke", opts);
    }
    if (tab === "people") {
      return userMode === "grant"
        ? t("bulkAccess.descriptionGrantUser", opts)
        : t("bulkAccess.descriptionRevokeUser", opts);
    }
    return allMode === "share"
      ? t("bulkAccess.descriptionAllShare", opts)
      : t("bulkAccess.descriptionAllRemove", opts);
  }, [tab, roleMode, userMode, allMode, count, resourceNoun, t]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bulkAccess.title")}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as "people" | "roles" | "all");
            setSelectedUserIds(new Set());
            setUserSearch("");
            setSelectedRoleIds(new Set());
          }}
        >
          <TabsBar>
            <TabsTrigger value="people">{t("share.people")}</TabsTrigger>
            <TabsTrigger value="roles">{t("share.roles")}</TabsTrigger>
            <TabsTrigger value="all">{t("bulkAccess.tabAllMembers")}</TabsTrigger>
          </TabsBar>

          <TabsContent value="people" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="userMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select
                value={userMode}
                onValueChange={(v) => {
                  setUserMode(v as "grant" | "revoke");
                  setSelectedUserIds(new Set());
                  setUserSearch("");
                }}
              >
                <SelectTrigger id="userMode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">{t("bulkAccess.grantAccess")}</SelectItem>
                  <SelectItem value="revoke">{t("bulkAccess.revokeAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {userMode === "revoke" && revocableUsers.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkAccess.noUserAccess")}</p>
            ) : (
              <>
                <div className="space-y-2">
                  <label htmlFor="userPicker" className="font-medium text-sm">
                    {t("share.people")}
                  </label>
                  <Combobox
                    multiple
                    id="userPicker"
                    items={userMode === "grant" ? availableUsers : revocableUsers}
                    value={[...selectedUserIds].map(String)}
                    onValueChange={(next) => setSelectedUserIds(new Set(next.map(Number)))}
                    // Granting searches the server; the granted are searched here.
                    onSearchChange={userMode === "grant" ? setUserSearch : undefined}
                    placeholder={
                      userMode === "grant"
                        ? t("bulkAccess.selectPeople")
                        : t("bulkAccess.selectPeopleToRevoke")
                    }
                    emptyMessage={t("share.noPeople")}
                    searchPlaceholder={t("share.searchPeople")}
                  />
                </div>
                {userMode === "grant" && (
                  <div className="space-y-2">
                    <label htmlFor="userLevel" className="font-medium text-sm">
                      {t("bulkAccess.permissionLevel")}
                    </label>
                    <Select value={level} onValueChange={(v) => setLevel(v as "read" | "write")}>
                      <SelectTrigger id="userLevel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="roles" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="roleMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select
                value={roleMode}
                onValueChange={(v) => {
                  setRoleMode(v as "grant" | "revoke");
                  setSelectedRoleIds(new Set());
                }}
              >
                <SelectTrigger id="roleMode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">{t("bulkAccess.grantAccess")}</SelectItem>
                  <SelectItem value="revoke">{t("bulkAccess.revokeAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {roleMode === "revoke" && revocableRoles.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkAccess.noRoleAccess")}</p>
            ) : (
              <>
                <div className="space-y-2">
                  <label htmlFor="rolePicker" className="font-medium text-sm">
                    {t("share.roles")}
                  </label>
                  <Combobox
                    multiple
                    id="rolePicker"
                    items={displayRoles.map((r) => ({
                      value: String(r.id),
                      label: r.displayName,
                      sublabel: initiativeIds.length > 1 ? r.initiativeName : undefined,
                    }))}
                    value={[...selectedRoleIds].map(String)}
                    onValueChange={(next) => setSelectedRoleIds(new Set(next.map(Number)))}
                    loading={roleMode === "grant" && roleQueries.some((query) => query.isLoading)}
                    placeholder={
                      roleMode === "grant"
                        ? t("bulkAccess.selectRoles")
                        : t("bulkAccess.selectRolesToRevoke")
                    }
                    emptyMessage={t("share.noRoles")}
                    searchPlaceholder={t("share.searchRoles")}
                  />
                </div>
                {roleMode === "grant" && (
                  <div className="space-y-2">
                    <label htmlFor="roleLevel" className="font-medium text-sm">
                      {t("bulkAccess.permissionLevel")}
                    </label>
                    <Select
                      value={roleLevel}
                      onValueChange={(v) => setRoleLevel(v as "read" | "write")}
                    >
                      <SelectTrigger id="roleLevel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="all" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="allMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select value={allMode} onValueChange={(v) => setAllMode(v as "share" | "remove")}>
                <SelectTrigger id="allMode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="share">{t("bulkAccess.shareAllMembers")}</SelectItem>
                  <SelectItem value="remove">{t("bulkAccess.removeAllMembersAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {allMode === "share" && (
              <div className="space-y-2">
                <label htmlFor="allLevel" className="font-medium text-sm">
                  {t("bulkAccess.permissionLevel")}
                </label>
                <Select value={allLevel} onValueChange={(v) => setAllLevel(v as "read" | "write")}>
                  <SelectTrigger id="allLevel">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("share.viewer")}</SelectItem>
                    <SelectItem value="write">{t("share.editor")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            <p className="text-muted-foreground text-xs">
              {allMode === "share"
                ? t("bulkAccess.shareAllMembersHint")
                : t("bulkAccess.removeAllMembersHint")}
            </p>
          </TabsContent>
        </Tabs>

        {tab === "roles" ? (
          <DialogFooter
            submitLabel={
              roleMode === "grant"
                ? t("bulkAccess.grantRoles", { count: selectedRoleCount })
                : t("bulkAccess.revokeRoles", { count: selectedRoleCount })
            }
            pendingLabel={t("bulkAccess.applying")}
            pending={isPending}
            disabled={!canApplyRoles}
            destructive={roleMode === "revoke"}
            onSubmit={handleApplyRoles}
          />
        ) : tab === "people" ? (
          <DialogFooter
            submitLabel={
              userMode === "grant"
                ? t("bulkAccess.grantPeople", { count: selectedUserCount })
                : t("bulkAccess.revokePeople", { count: selectedUserCount })
            }
            pendingLabel={t("bulkAccess.applying")}
            pending={isPending}
            disabled={!canApplyUsers}
            destructive={userMode === "revoke"}
            onSubmit={handleApply}
          />
        ) : (
          <DialogFooter
            submitLabel={
              allMode === "share"
                ? t("bulkAccess.shareAllMembers")
                : t("bulkAccess.removeAllMembersAccess")
            }
            pendingLabel={t("bulkAccess.applying")}
            pending={isPending}
            destructive={allMode === "remove"}
            onSubmit={handleApplyAllMembers}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
