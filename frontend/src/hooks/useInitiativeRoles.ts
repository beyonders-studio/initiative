import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  InitiativeDefaultsRead,
  InitiativeDefaultsUpdate,
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createInitiativeRole,
  deleteInitiativeRole,
  getGetInitiativeDefaultsQueryKey,
  getInitiativeDefaults,
  getListInitiativeRolesQueryKey,
  listInitiativeRoles,
  updateInitiativeDefaults,
  updateInitiativeRole,
} from "@/api/generated/initiatives/initiatives";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { TOOLS, toolCreatePermission, toolPascalPlural, toolViewPermission } from "@/lib/tools";

export const useInitiativeRoles = (initiativeId: number | null) => {
  const communityId = useActiveCommunityId();
  return useQuery<InitiativeRoleRead[]>({
    queryKey: getListInitiativeRolesQueryKey(communityId, initiativeId!),
    queryFn: () => listInitiativeRoles(communityId, initiativeId!),
    enabled: !!initiativeId,
    staleTime: 30 * 1000,
  });
};

export const useCreateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const communityId = useActiveCommunityId();

  return useMutation({
    mutationFn: async (data: InitiativeRoleCreate) => {
      return createInitiativeRole(communityId, initiativeId, data);
    },
    onSuccess: () => {
      toast.success(t("settings.roleCreated"));
      void invalidate(q.initiativeRoles(initiativeId));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleCreateError"));
    },
  });
};

export const useUpdateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const communityId = useActiveCommunityId();

  return useMutation({
    mutationFn: async ({ roleId, data }: { roleId: number; data: InitiativeRoleUpdate }) => {
      return updateInitiativeRole(communityId, initiativeId, roleId, data);
    },
    onSuccess: () => {
      toast.success(t("settings.roleUpdated"));
      void invalidate(q.initiativeRoles(initiativeId), q.allInitiatives());
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleUpdateError"));
    },
  });
};

/**
 * Grant one tool's view permission to every role that isn't a manager.
 *
 * The other half of turning a tool on: the master switch makes the initiative
 * offer the tool, this makes the roles able to see it. Manager roles are
 * skipped because they already see everything, and the create permission is
 * left alone — being able to read a board and being able to add to it are
 * separate decisions, and this one only answers the first.
 *
 * Three things this is careful about, because the whole point of the feature
 * is that a tool is never quietly visible to fewer people than was asked for:
 *
 * - **The roster is read here, not passed in.** A cached list that is still
 *   loading or failed to load is an empty list, and granting to nobody must
 *   not report success. Reading it as part of the mutation means a roster that
 *   cannot be fetched fails the grant instead.
 * - **Only the one key is sent.** The endpoint merges the keys it is given, so
 *   resending a whole snapshot could write back a permission somebody else
 *   changed since it was read.
 * - **Every role is attempted.** One role's failure does not skip the rest;
 *   the error is raised after the others have been tried, so a retry has less
 *   to do and the audience line already reflects who really has it.
 */
export const useGrantToolToRoles = (initiativeId: number) => {
  const communityId = useActiveCommunityId();

  return useMutation({
    mutationFn: async ({ tool }: { tool: Tool }) => {
      const key = toolViewPermission(tool);
      const roles = await listInitiativeRoles(communityId, initiativeId);
      const needsGrant = roles.filter(
        (role) => !role.is_manager && !(role.permissions[key] ?? false)
      );
      const results = await Promise.allSettled(
        needsGrant.map((role) =>
          updateInitiativeRole(communityId, initiativeId, role.id, { permissions: { [key]: true } })
        )
      );
      const failed = results.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      return needsGrant.length;
    },
    onSettled: () => {
      void invalidate(q.initiativeRoles(initiativeId), q.allInitiatives());
    },
  });
};

/**
 * What the ordinary roles may do with a set of tools — the question a brand-new
 * initiative has to answer and cannot answer for itself.
 *
 * The built-in `member` role ships view-only on projects and files and
 * `create_*` off everywhere (the backend's DEFAULT_PERMISSION_VALUES). So an
 * initiative created with, say, a calendar has that calendar on for its
 * managers and invisible to everybody else — the state `ToolAudience` warns
 * about after the fact. The create wizard asks once, up front, and this applies
 * the answer.
 *
 * "managers" writes nothing, which is that default. Manager roles are skipped
 * because they hold every permission by construction.
 */
export const useGrantToolsToMembers = () => {
  const communityId = useActiveCommunityId();

  return useMutation({
    mutationFn: async ({
      initiativeId,
      tools,
      audience,
    }: {
      /** Passed per call, not bound to the hook: the caller is the create
       *  wizard, and the initiative does not exist at the render that set this
       *  mutation up. Closing over an id from state would send the writes to
       *  whatever that state held a render ago — which is nothing. */
      initiativeId: number;
      tools: Tool[];
      audience: "create" | "view" | "managers";
    }) => {
      if (tools.length === 0) return 0;
      // Written for every chosen tool, in all three answers. "Managers only"
      // is a revoke, not a no-op: the built-in member role arrives holding
      // projects and files, so leaving it alone would answer "managers
      // only" with members who can still see both.
      const permissions: Record<string, boolean> = {};
      for (const tool of tools) {
        permissions[toolViewPermission(tool)] = audience !== "managers";
        permissions[toolCreatePermission(tool)] = audience === "create";
      }
      const roles = await listInitiativeRoles(communityId, initiativeId);
      const ordinary = roles.filter((role) => !role.is_manager);
      const results = await Promise.allSettled(
        ordinary.map((role) =>
          updateInitiativeRole(communityId, initiativeId, role.id, { permissions })
        )
      );
      const failed = results.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      return ordinary.length;
    },
    onSettled: (_data, _error, variables) => {
      void invalidate(q.initiativeRoles(variables.initiativeId), q.allInitiatives());
    },
  });
};

export const useDeleteRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const communityId = useActiveCommunityId();

  return useMutation({
    mutationFn: async (roleId: number) => {
      await deleteInitiativeRole(communityId, initiativeId, roleId);
    },
    onSuccess: () => {
      toast.success(t("settings.roleDeleted"));
      void invalidate(q.initiativeRoles(initiativeId));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleDeleteError"));
    },
  });
};

/** Role permissions that are not a tool's view/create pair: capabilities inside
 *  a tool. Off for an ordinary role; managers always hold them. */
export const EXTRA_PERMISSION_KEYS = [
  "dashboards_run_as_initiative",
] as const satisfies readonly PermissionKey[];

// i18n-based permission label keys (use with t()) — one view/create pair per
// tool, derived: settings.permissions.view{PascalPlural} / create{PascalPlural},
// plus settings.permissions.<key> for each extra key.
export const PERMISSION_LABEL_KEYS: Record<PermissionKey, string> = Object.fromEntries([
  ...TOOLS.flatMap((tool) => [
    [toolViewPermission(tool), `settings.permissions.view${toolPascalPlural(tool)}`],
    [toolCreatePermission(tool), `settings.permissions.create${toolPascalPlural(tool)}`],
  ]),
  ...EXTRA_PERMISSION_KEYS.map((key) => [key, `settings.permissions.${key}`]),
]) as Record<PermissionKey, string>;

/** What the community sets for every initiative in it: the tool switches and
 *  member permissions an initiative's managers see as set, and whether they
 *  may add roles. */
export const useInitiativeDefaults = () => {
  const communityId = useActiveCommunityId();
  return useQuery<InitiativeDefaultsRead>({
    queryKey: getGetInitiativeDefaultsQueryKey(communityId),
    queryFn: () => getInitiativeDefaults(communityId),
    enabled: communityId > 0,
    staleTime: 30 * 1000,
  });
};

/** Change what every initiative uses. The community's admins only. */
export const useSetInitiativeDefaults = () => {
  const { t } = useTranslation("initiatives");
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: InitiativeDefaultsUpdate) => updateInitiativeDefaults(communityId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetInitiativeDefaultsQueryKey(communityId),
      });
      // Each initiative answers with its switches as they now stand.
      void invalidate(q.allInitiatives());
      toast.success(t("communityDefaults.saved"));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:communityDefaults.error"));
    },
  });
};
