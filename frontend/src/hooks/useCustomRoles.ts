import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  assignCustomRole,
  createCustomRole,
  deleteCustomRole,
  getListCustomRoleHoldersQueryKey,
  getListCustomRolesQueryKey,
  getReadHeldSurfacesQueryKey,
  listCustomRoleHolders,
  listCustomRoles,
  readHeldSurfaces,
  updateCustomRole,
} from "@/api/generated/custom-roles/custom-roles";
import {
  AdminSurface,
  type CustomRoleCreate,
  type CustomRoleHolder,
  type CustomRoleRead,
  type CustomRoleUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/** Every part of running a community, in the order the editor lists them. */
export const ADMIN_SURFACES: readonly AdminSurface[] = Object.values(AdminSurface);

/** The parts a role on the member rung may hold (the backend's
 *  `MEMBER_ROLE_SURFACES`). */
export const MEMBER_ROLE_SURFACES: readonly AdminSurface[] = [
  AdminSurface.profile,
  AdminSurface.invites,
  AdminSurface.members,
  AdminSurface.community_calendars,
  AdminSurface.usage,
];

/** The parts a live settings grant answers for, at the rung it lends: the
 *  community's own configuration routes. */
const SETTINGS_GRANT_SURFACES: readonly AdminSurface[] = [
  AdminSurface.profile,
  AdminSurface.invites,
  AdminSurface.members,
  AdminSurface.usage,
  AdminSurface.roles,
];

const STALE_TIME = 30 * 1000;

/** The community's custom roles. Anybody in it may read them. */
export const useCustomRoles = (options?: { enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  return useQuery<CustomRoleRead[]>({
    queryKey: getListCustomRolesQueryKey(communityId),
    queryFn: () => listCustomRoles(communityId),
    enabled: communityId > 0 && (options?.enabled ?? true),
    staleTime: STALE_TIME,
  });
};

/** Who holds which custom role. */
export const useCustomRoleHolders = (options?: { enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  return useQuery<CustomRoleHolder[]>({
    queryKey: getListCustomRoleHoldersQueryKey(communityId),
    queryFn: () => listCustomRoleHolders(communityId),
    enabled: communityId > 0 && (options?.enabled ?? true),
    staleTime: STALE_TIME,
  });
};

export interface HeldSurfaces {
  /** Whether the server's answer is still on its way. */
  isLoading: boolean;
  /** Whether the reader holds `surface` in the community. */
  holds: (surface: AdminSurface) => boolean;
  /** Whether the reader holds any part of running it. */
  holdsAny: boolean;
  /** Whether the reader may change what they hold, not only read it. */
  writes: boolean;
}

/**
 * The parts of running a community the reader holds: every one for an admin
 * with no custom role, a role's otherwise, none for a plain member. A live
 * settings grant answers for the configuration parts at the rung it lends.
 *
 * Until the server answers (or where it cannot), the rung answers: an admin
 * holds every part, a member none. A caller that must not show an admin a part
 * their role takes away waits for `isLoading` to clear.
 *
 * `community` defaults to the active one.
 */
export const useHeldSurfaces = (
  community?: CommunityEntry | null,
  options?: { enabled?: boolean }
): HeldSurfaces => {
  const { activeCommunity } = useCommunities();
  const entry = community === undefined ? activeCommunity : community;
  const communityId = entry?.id ?? 0;
  // A community reached only by a grant has no membership to hold a role by.
  const asked = communityId > 0 && entry?.accessType !== "grant" && (options?.enabled ?? true);
  const query = useQuery({
    queryKey: getReadHeldSurfacesQueryKey(communityId),
    queryFn: () => readHeldSurfaces(communityId),
    enabled: asked,
    staleTime: STALE_TIME,
    // Never another community's answer while this one's is on its way.
    placeholderData: undefined,
  });

  const administers = Boolean(entry?.can.administer);
  const configures = Boolean(entry?.can.configure);
  const lent = Boolean(entry?.grantSettingsLevel);
  const rungAnswer = entry?.can.administer_content && entry.accessType !== "grant";
  const own = useMemo<readonly AdminSurface[]>(
    () => query.data?.surfaces ?? (rungAnswer ? ADMIN_SURFACES : []),
    [query.data, rungAnswer]
  );
  const holds = useCallback(
    (surface: AdminSurface) =>
      own.includes(surface) || (lent && SETTINGS_GRANT_SURFACES.includes(surface)),
    [own, lent]
  );
  const holdsAny = ADMIN_SURFACES.some(holds);
  return {
    isLoading: asked && query.isPending,
    holds,
    holdsAny,
    // The admin rung writes where the server says it may; a member writes
    // what their role gives them.
    writes: configures || (!administers && own.length > 0),
  };
};

export const useCreateCustomRole = () => {
  const { t } = useTranslation("settings");
  const communityId = useActiveCommunityId();
  return useMutation({
    mutationFn: (data: CustomRoleCreate) => createCustomRole(communityId, data),
    onSuccess: () => {
      toast.success(t("customRoles.created"));
      void invalidate(q.customRoles());
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "settings:customRoles.createError"));
    },
  });
};

export const useUpdateCustomRole = () => {
  const { t } = useTranslation("settings");
  const communityId = useActiveCommunityId();
  return useMutation({
    mutationFn: ({ roleId, data }: { roleId: number; data: CustomRoleUpdate }) =>
      updateCustomRole(communityId, roleId, data),
    onSuccess: () => {
      toast.success(t("customRoles.updated"));
      // The reader may hold the role they changed.
      void invalidate(q.customRoles());
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "settings:customRoles.updateError"));
    },
  });
};

export const useDeleteCustomRole = () => {
  const { t } = useTranslation("settings");
  const communityId = useActiveCommunityId();
  return useMutation({
    mutationFn: (roleId: number) => deleteCustomRole(communityId, roleId),
    onSuccess: () => {
      toast.success(t("customRoles.deleted"));
      void invalidate(q.customRoles());
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "settings:customRoles.deleteError"));
    },
  });
};

/** Give a member a custom role in place of theirs, or take theirs off (`null`). */
export const useAssignCustomRole = () => {
  const { t } = useTranslation("settings");
  const communityId = useActiveCommunityId();
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId: number | null }) =>
      assignCustomRole(communityId, userId, { role_id: roleId }),
    onSuccess: () => {
      toast.success(t("customRoles.assigned"));
      void invalidate(q.customRoles());
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "settings:customRoles.assignError"));
    },
  });
};
