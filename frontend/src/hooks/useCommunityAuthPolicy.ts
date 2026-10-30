import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getListCommunityLoginProvidersQueryKey,
  getListLoginProvidersQueryKey,
  listCommunityLoginProviders,
  listLoginProviders,
} from "@/api/generated/auth/auth";
import {
  getCommunityAuthSettings,
  getGetCommunityAuthSettingsQueryKey,
  updateCommunityAuthSettings,
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
  listCommunityClaimRules,
  listCommunityProviderConnections,
  listConnectableProviders,
  listCustomRoleClaimRules,
  orderCustomRoleClaimRules,
  updateCommunityProviderConnection,
} from "@/api/generated/community-provider-connections/community-provider-connections";
import type {
  CommunityAuthSettingsRead,
  CommunityAuthSettingsUpdate,
  CommunityClaimRuleCreate,
  CommunityClaimRulesResponse,
  CommunityProviderConnectionCreate,
  CommunityProviderConnectionRead,
  CommunityProviderConnectionUpdate,
  ConnectableProviderRead,
  CustomRoleClaimRuleCreate,
  CustomRoleClaimRuleRead,
  LoginProvidersResponse,
} from "@/api/generated/initiativeAPI.schemas";
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
  return useQuery<LoginProvidersResponse>({
    queryKey: getListCommunityLoginProvidersQueryKey(communityId),
    queryFn: () => listCommunityLoginProviders(communityId),
    staleTime: 60_000,
    enabled: communityId > 0,
    ...options,
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
  return useQuery<CommunityAuthSettingsRead>({
    queryKey: getGetCommunityAuthSettingsQueryKey(communityId),
    queryFn: () => getCommunityAuthSettings(communityId),
    enabled: communityId > 0,
    refetchOnMount: "always",
    ...options,
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
  return useQuery<CommunityProviderConnectionRead[]>({
    queryKey: getListCommunityProviderConnectionsQueryKey(communityId),
    queryFn: () => listCommunityProviderConnections(communityId),
    enabled: communityId > 0,
    ...options,
  });
};

/** The providers this community may choose from — on offer, or already in use. */
export const useConnectableProviders = (
  communityId: number,
  options?: QueryOpts<ConnectableProviderRead[]>
) => {
  return useQuery<ConnectableProviderRead[]>({
    queryKey: getListConnectableProvidersQueryKey(communityId),
    queryFn: () => listConnectableProviders(communityId),
    enabled: communityId > 0,
    ...options,
  });
};

const useInvalidateConnections = (communityId: number) => {
  const queryClient = useQueryClient();
  // Three consumers read this: the list, the picker (a provider already
  // connected is still offered, so it has to know), and the public login
  // listing — which feeds the policy page's "sign in with it first" prompt
  // and the step-up dialog. Without the last one a freshly connected provider
  // cannot be required until the cache expires. The rules list reads it too:
  // whether the deployment's rules for a provider apply here follows the
  // connection's acceptance.
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListCommunityClaimRulesQueryKey(communityId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListCommunityProviderConnectionsQueryKey(communityId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListConnectableProvidersQueryKey(communityId),
    });
    void queryClient.invalidateQueries({
      queryKey: getListCommunityLoginProvidersQueryKey(communityId),
    });
  };
};

export const useConnectProvider = (communityId: number) => {
  const invalidate = useInvalidateConnections(communityId);
  return useMutation({
    mutationFn: (data: CommunityProviderConnectionCreate) =>
      createCommunityProviderConnection(communityId, data),
    onSuccess: invalidate,
  });
};

export const useUpdateProviderConnection = (communityId: number) => {
  const invalidate = useInvalidateConnections(communityId);
  return useMutation({
    mutationFn: ({
      connectionId,
      data,
    }: {
      connectionId: number;
      data: CommunityProviderConnectionUpdate;
    }) => updateCommunityProviderConnection(communityId, connectionId, data),
    onSuccess: invalidate,
  });
};

export const useDisconnectProvider = (communityId: number) => {
  const invalidate = useInvalidateConnections(communityId);
  return useMutation({
    mutationFn: (connectionId: number) =>
      deleteCommunityProviderConnection(communityId, connectionId),
    onSuccess: invalidate,
  });
};

/** Where this community places the people its providers vouch for. */
export const useCommunityClaimRules = (
  communityId: number,
  options?: QueryOpts<CommunityClaimRulesResponse>
) => {
  return useQuery<CommunityClaimRulesResponse>({
    queryKey: getListCommunityClaimRulesQueryKey(communityId),
    queryFn: () => listCommunityClaimRules(communityId),
    enabled: communityId > 0,
    ...options,
  });
};

const useInvalidateClaimRules = (communityId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListCommunityClaimRulesQueryKey(communityId),
    });
  };
};

export const useCreateClaimRule = (communityId: number) => {
  const invalidate = useInvalidateClaimRules(communityId);
  return useMutation({
    mutationFn: (data: CommunityClaimRuleCreate) => createCommunityClaimRule(communityId, data),
    onSuccess: invalidate,
  });
};

export const useDeleteClaimRule = (communityId: number) => {
  const invalidate = useInvalidateClaimRules(communityId);
  return useMutation({
    mutationFn: (ruleId: number) => deleteCommunityClaimRule(communityId, ruleId),
    onSuccess: invalidate,
  });
};

/** Which custom role each group gives, in the order a sign-in reads them. */
export const useCustomRoleClaimRules = (
  communityId: number,
  options?: QueryOpts<CustomRoleClaimRuleRead[]>
) => {
  return useQuery<CustomRoleClaimRuleRead[]>({
    queryKey: getListCustomRoleClaimRulesQueryKey(communityId),
    queryFn: () => listCustomRoleClaimRules(communityId),
    enabled: communityId > 0,
    ...options,
  });
};

const useInvalidateCustomRoleClaimRules = (communityId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getListCustomRoleClaimRulesQueryKey(communityId),
    });
  };
};

export const useCreateCustomRoleClaimRule = (communityId: number) => {
  const invalidate = useInvalidateCustomRoleClaimRules(communityId);
  return useMutation({
    mutationFn: (data: CustomRoleClaimRuleCreate) => createCustomRoleClaimRule(communityId, data),
    onSuccess: invalidate,
  });
};

/** Put the rules in a new order: every rule's id, once. */
export const useOrderCustomRoleClaimRules = (communityId: number) => {
  const invalidate = useInvalidateCustomRoleClaimRules(communityId);
  return useMutation({
    mutationFn: (ruleIds: number[]) =>
      orderCustomRoleClaimRules(communityId, { rule_ids: ruleIds }),
    onSuccess: invalidate,
  });
};

export const useDeleteCustomRoleClaimRule = (communityId: number) => {
  const invalidate = useInvalidateCustomRoleClaimRules(communityId);
  return useMutation({
    mutationFn: (ruleId: number) => deleteCustomRoleClaimRule(communityId, ruleId),
    onSuccess: invalidate,
  });
};
