/**
 * One installed plug-in, its connections, and the actions that change them.
 *
 * The detail read is per viewer: a member's own connect state comes back on
 * their request and nobody else's does, so there is no client-side filtering to
 * get wrong. Every mutation invalidates both this plug-in and the community's plug-in list,
 * because a connection change can flip whether the install still needs
 * configuring — which the list shows.
 */

import { keepPreviousData, useMutation } from "@tanstack/react-query";

import type {
  CommunityPluginConfigUpdateValues,
  CommunityPluginConnectStart,
  CommunityPluginConsentRead,
  CommunityPluginDetail,
  CommunityPluginUpgrade,
  ConsentAccess,
} from "@/api/generated/initiativeAPI.schemas";
import {
  blockMemberConnection,
  connectCommunityPlugin,
  declineCommunityPluginUpgrade,
  disconnectCommunityPlugin,
  grantMyConsent,
  revokeAllMemberConnections,
  revokeAllMemberConsents,
  revokeMemberConnection,
  revokeMemberConsents,
  revokeMyConsent,
  unblockMemberConnection,
  updateCommunityPluginConfig,
  updateCommunityPluginSetting,
  upgradeCommunityPlugin,
  useGetCommunityPlugin,
  useListCommunityPluginMembers,
} from "@/api/generated/plugins/plugins";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

export const useCommunityPluginDetail = (pluginId: number) =>
  useGetCommunityPlugin(useActiveCommunityId(), pluginId);

/** Community admins only; the server refuses everyone else. */
/** One page of the members who connected to the plug-in or answered it. */
export const useCommunityPluginMembers = (pluginId: number, page: number, enabled: boolean) => {
  const communityId = useActiveCommunityId();
  return useListCommunityPluginMembers(
    communityId,
    pluginId,
    { page },
    { query: { placeholderData: keepPreviousData, enabled } }
  );
};

// Every mutation below refreshes the same three reads through the shared
// `() => invalidate(q.plugins())`, so a connection change cannot leave the settings page, the
// Members view and the sidebar disagreeing about what is configured — and a
// write from here refreshes exactly what a frame off the realtime bus does.

/** Values keyed by connection, then field. A key sent as `null` clears it; a
 *  key left out is untouched. */
export const useUpdatePluginConfig = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginDetail, unknown, CommunityPluginConfigUpdateValues>({
    mutationFn: (values) => updateCommunityPluginConfig(communityId, pluginId, { values }),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export interface PluginSettingValue {
  key: string;
  /** `null` clears a setting that is not unique. */
  value: string | null;
}

/** One of the install's settings. */
export const useUpdatePluginSetting = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginDetail, unknown, PluginSettingValue>({
    mutationFn: ({ key, value }) =>
      updateCommunityPluginSetting(communityId, pluginId, key, { value }),
    onSuccess: () => invalidate(q.plugins()),
  });
};

/** Apply the offered version; pass the seat's consent when it asks for more. */
export const useUpgradePlugin = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginDetail, unknown, CommunityPluginUpgrade | undefined>({
    mutationFn: (consent) => upgradeCommunityPlugin(communityId, pluginId, consent),
    // Refreshed on failure too: a refusal means the offer moved, and the panel
    // should show what is offered now.
    onSettled: () => invalidate(q.plugins()),
  });
};

/** Keep the pinned version and stop being asked about this one. */
export const useDeclinePluginUpgrade = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginDetail, unknown, string>({
    mutationFn: (version) => declineCommunityPluginUpgrade(communityId, pluginId, { version }),
    onSettled: () => invalidate(q.plugins()),
  });
};

export const useConnectPlugin = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginConnectStart, unknown, string>({
    mutationFn: (connectionId) => connectCommunityPlugin(communityId, pluginId, connectionId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export const useDisconnectPlugin = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, string>({
    mutationFn: (connectionId) => disconnectCommunityPlugin(communityId, pluginId, connectionId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export interface MemberConnectionTarget {
  userId: number;
  connectionId: string;
}

export const useRevokeMemberConnection = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, MemberConnectionTarget>({
    mutationFn: ({ userId, connectionId }) =>
      revokeMemberConnection(communityId, pluginId, userId, connectionId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export const useBlockMemberConnection = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, MemberConnectionTarget & { blocked: boolean }>({
    // One mutation for both directions: the button is a toggle, and splitting
    // it would mean two hooks that must stay in step about what "blocked" means.
    mutationFn: ({ userId, connectionId, blocked }) =>
      blocked
        ? unblockMemberConnection(communityId, pluginId, userId, connectionId)
        : blockMemberConnection(communityId, pluginId, userId, connectionId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export const useRevokeAllConnections = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConnections(communityId, pluginId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

// --- acting as a member ------------------------------------------------------

/** A community admin ending every answer one member gave. There is deliberately
 *  no counterpart that gives one — governance runs one way here. */
export const useRevokeMemberConsents = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, number>({
    mutationFn: (userId) => revokeMemberConsents(communityId, pluginId, userId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

/** Stop the plug-in acting as anybody, without uninstalling it. */
export const useRevokeAllConsents = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, void>({
    mutationFn: () => revokeAllMemberConsents(communityId, pluginId),
    onSuccess: () => invalidate(q.plugins()),
  });
};

export interface ConsentAnswer {
  consentId: number;
  access: ConsentAccess;
}

/** Answer one of the plug-in's requests to act as you. */
export const useGrantPluginConsent = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<CommunityPluginConsentRead, unknown, ConsentAnswer>({
    mutationFn: ({ consentId, access }) =>
      grantMyConsent(communityId, pluginId, consentId, {
        access,
      }),
    onSuccess: () => invalidate(q.plugins()),
  });
};

/** Decline one, or withdraw what you allowed. */
export const useRevokePluginConsent = (pluginId: number) => {
  const communityId = useActiveCommunityId();
  return useMutation<void, unknown, number>({
    mutationFn: (consentId) => revokeMyConsent(communityId, pluginId, consentId),
    onSuccess: () => invalidate(q.plugins()),
  });
};
