import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListCommunityLoginProvidersQueryKey,
  getListLoginProvidersQueryKey,
  listLoginProviders,
  useListCommunityLoginProviders,
} from "@/api/generated/auth/auth";
import {
  getGetCommunityAuthSettingsQueryKey,
  updateCommunityAuthSettings,
  useGetCommunityAuthSettings,
} from "@/api/generated/communities/communities";
import {
  createCommunityClaimRule,
  createCommunityProviderConnection,
  createCustomRoleClaimRule,
  deleteCommunityClaimRule,
  deleteCommunityProviderConnection,
  deleteCustomRoleClaimRule,
  getListCommunityClaimRulesQueryKey,
  getListCommunityProviderConnectionsQueryKey,
  getListConnectableProvidersQueryKey,
  getListCustomRoleClaimRulesQueryKey,
  orderCustomRoleClaimRules,
  updateCommunityClaimRule,
  updateCommunityProviderConnection,
  updateCustomRoleClaimRule,
  useListCommunityClaimRules,
  useListCommunityProviderConnections,
  useListConnectableProviders,
  useListCustomRoleClaimRules,
} from "@/api/generated/community-provider-connections/community-provider-connections";
import type {
  CommunityAuthSettingsRead,
  CommunityAuthSettingsUpdate,
  CommunityClaimRuleCreate,
  CommunityClaimRulesResponse,
  CommunityClaimRuleUpdate,
  CommunityProviderConnectionCreate,
  CommunityProviderConnectionRead,
  CommunityProviderConnectionUpdate,
  ConnectableProviderRead,
  CustomRoleClaimRuleCreate,
  CustomRoleClaimRuleRead,
  CustomRoleClaimRuleUpdate,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { QueryOpts } from "@/types/query";

/** The sign-in providers the login page offers (non-secret metadata). */
export const useLoginProviders = (options?: QueryOpts<LoginProvidersResponse>) => {
  return useQuery<LoginProvidersResponse>({
    queryKey: getListLoginProvidersQueryKey(),
    queryFn: () => listLoginProviders(),
    staleTime: 60_000,
    ...options,
  });
};

/**
 * One community's public sign-in providers (non-secret metadata with
 * community-addressed login URLs; empty outside per-community auth posture).
 */
export const useCommunityLoginProviders = (
  communityId: number,
  options?: QueryOpts<LoginProvidersResponse>
) => {
  return useListCommunityLoginProviders(communityId, {
    query: { staleTime: 60_000, enabled: communityId > 0, ...options },
  });
};

/**
 * The complete Authentication settings available to a settings superadmin.
 *
 * Read again each time the page opens: it carries the deployment's answers
 * beside the community's, and those are written from the platform's pages.
 */
export const useCommunityAuthSettings = (
  communityId: number,
  options?: QueryOpts<CommunityAuthSettingsRead>
) => {
  return useGetCommunityAuthSettings(communityId, {
    query: { enabled: communityId > 0, refetchOnMount: "always", ...options },
  });
};

/**
 * Change any of the seat page's rules, then read them all back. Two switches
 * saved together can answer out of order, so the page rereads what the server
 * holds rather than taking either answer as the latest.
 */
export const useUpdateCommunityAuthSettings = (communityId: number) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CommunityAuthSettingsUpdate) =>
      updateCommunityAuthSettings(communityId, data),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: getGetCommunityAuthSettingsQueryKey(communityId),
      }),
  });
};

/** Which of the platform's providers this community counts as its own. */
export const useCommunityProviderConnections = (
  communityId: number,
  options?: QueryOpts<CommunityProviderConnectionRead[]>
) => {
  return useListCommunityProviderConnections(communityId, {
    query: { enabled: communityId > 0, ...options },
  });
};

/** The providers this community may choose from — on offer, or already in use. */
export const useConnectableProviders = (
  communityId: number,
  options?: QueryOpts<ConnectableProviderRead[]>
) => {
  return useListConnectableProviders(communityId, {
    query: { enabled: communityId > 0, ...options },
  });
};

// Three consumers read this: the list, the picker (a provider already
// connected is still offered, so it has to know), and the public login
// listing — which feeds the policy page's "sign in with it first" prompt
// and the step-up dialog. Without the last one a freshly connected provider
// cannot be required until the cache expires. The rules list reads it too:
// whether the deployment's rules for a provider apply here follows the
// connection's acceptance. And the seat's settings count, per connected
// provider, who has never signed in through it.
const invalidateConnections = (communityId: number) => {
  for (const queryKey of [
    getGetCommunityAuthSettingsQueryKey(communityId),
    getListCommunityClaimRulesQueryKey(communityId),
    getListCommunityProviderConnectionsQueryKey(communityId),
    getListConnectableProvidersQueryKey(communityId),
    getListCommunityLoginProvidersQueryKey(communityId),
  ]) {
    void queryClient.invalidateQueries({ queryKey });
  }
};

export const useConnectProvider = (communityId: number) =>
  useApiMutation({
    mutationFn: (data: CommunityProviderConnectionCreate) =>
      createCommunityProviderConnection(communityId, data),
    invalidate: () => invalidateConnections(communityId),
    errorKey: "settings:communityAuth.connections.connectError",
  });

export const useUpdateProviderConnection = (communityId: number) =>
  useApiMutation({
    mutationFn: ({
      connectionId,
      data,
    }: {
      connectionId: number;
      data: CommunityProviderConnectionUpdate;
    }) => updateCommunityProviderConnection(communityId, connectionId, data),
    invalidate: () => invalidateConnections(communityId),
    errorKey: "settings:communityAuth.connections.connectError",
  });

export const useDisconnectProvider = (communityId: number) =>
  useApiMutation({
    mutationFn: (connectionId: number) =>
      deleteCommunityProviderConnection(communityId, connectionId),
    invalidate: () => invalidateConnections(communityId),
    errorKey: "settings:communityAuth.connections.connectError",
  });

/** Where this community places the people its providers vouch for. */
export const useCommunityClaimRules = (
  communityId: number,
  options?: QueryOpts<CommunityClaimRulesResponse>
) => {
  return useListCommunityClaimRules(communityId, {
    query: { enabled: communityId > 0, ...options },
  });
};

const invalidateClaimRules = (communityId: number) =>
  queryClient.invalidateQueries({ queryKey: getListCommunityClaimRulesQueryKey(communityId) });

export const useCreateClaimRule = (communityId: number) =>
  useApiMutation({
    mutationFn: (data: CommunityClaimRuleCreate) => createCommunityClaimRule(communityId, data),
    invalidate: () => invalidateClaimRules(communityId),
    errorKey: "settings:communityAuth.rules.addError",
  });

export const useUpdateClaimRule = (communityId: number) =>
  useApiMutation({
    mutationFn: ({ ruleId, data }: { ruleId: number; data: CommunityClaimRuleUpdate }) =>
      updateCommunityClaimRule(communityId, ruleId, data),
    invalidate: () => invalidateClaimRules(communityId),
    errorKey: "settings:communityAuth.rules.saveError",
  });

export const useDeleteClaimRule = (communityId: number) =>
  useApiMutation({
    mutationFn: (ruleId: number) => deleteCommunityClaimRule(communityId, ruleId),
    invalidate: () => invalidateClaimRules(communityId),
    errorKey: "settings:communityAuth.rules.removeError",
  });

/** Which custom role each group gives, in the order a sign-in reads them. */
export const useCustomRoleClaimRules = (
  communityId: number,
  options?: QueryOpts<CustomRoleClaimRuleRead[]>
) => {
  return useListCustomRoleClaimRules(communityId, {
    query: { enabled: communityId > 0, ...options },
  });
};

/** Refetch the rules. Run as a mutation's `onSuccess`, which it waits on, so
 *  it stays pending until the new order is in and the next move is built from it. */
const refetchCustomRoleClaimRules = (communityId: number) =>
  queryClient.invalidateQueries({ queryKey: getListCustomRoleClaimRulesQueryKey(communityId) });

export const useCreateCustomRoleClaimRule = (communityId: number) =>
  useApiMutation(
    {
      mutationFn: (data: CustomRoleClaimRuleCreate) => createCustomRoleClaimRule(communityId, data),
      errorKey: "settings:customRoleRules.addError",
    },
    { onSuccess: () => refetchCustomRoleClaimRules(communityId) }
  );

export const useUpdateCustomRoleClaimRule = (communityId: number) =>
  useApiMutation(
    {
      mutationFn: ({ ruleId, data }: { ruleId: number; data: CustomRoleClaimRuleUpdate }) =>
        updateCustomRoleClaimRule(communityId, ruleId, data),
      errorKey: "settings:customRoleRules.saveError",
    },
    { onSuccess: () => refetchCustomRoleClaimRules(communityId) }
  );

/** Put the rules in a new order: every rule's id, once. */
export const useOrderCustomRoleClaimRules = (communityId: number) =>
  useApiMutation(
    {
      mutationFn: (ruleIds: number[]) =>
        orderCustomRoleClaimRules(communityId, { rule_ids: ruleIds }),
      errorKey: "settings:customRoleRules.orderError",
    },
    { onSuccess: () => refetchCustomRoleClaimRules(communityId) }
  );

export const useDeleteCustomRoleClaimRule = (communityId: number) =>
  useApiMutation(
    {
      mutationFn: (ruleId: number) => deleteCustomRoleClaimRule(communityId, ruleId),
      errorKey: "settings:customRoleRules.removeError",
    },
    { onSuccess: () => refetchCustomRoleClaimRules(communityId) }
  );
