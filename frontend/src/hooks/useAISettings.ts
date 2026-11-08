import { useMutation, useQuery } from "@tanstack/react-query";

import {
  createCommunityConnection,
  createPlatformConnection,
  deleteCommunityConnection,
  deletePlatformConnection,
  fetchCommunityConnectionModels,
  fetchPlatformConnectionModels,
  getGetPlatformAiModeQueryKey,
  getListCommunityConnectionsQueryKey,
  getListPlatformConnectionsQueryKey,
  getPlatformAiMode,
  listCommunityConnections,
  listPlatformConnections,
  testCommunityConnection,
  testPlatformConnection,
  updateCommunityConnection,
  updatePlatformAiMode,
  updatePlatformConnection,
} from "@/api/generated/ai-settings/ai-settings";
import type {
  AIConnectionCreate,
  AIConnectionResponse,
  AIConnectionTestResponse,
  AIConnectionUpdate,
  AIModelsResponse,
  ConnectionScope,
  PlatformAIModeResponse,
  PlatformAIModeUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** A connection mutation touched the active connection list — refresh both the
 * owning admin's list and every member surface that resolves through it. */
const invalidateConnectionSurfaces = (scope: ConnectionScope) =>
  Promise.all([
    scope === "platform"
      ? invalidate(q.platformAIConnections())
      : invalidate(q.communityAIConnections()),
    invalidate(q.resolvedAISettings()),
  ]);

// ── Platform mode (personal / platform) ───────────────────────────────────────

export const usePlatformAIMode = (options?: QueryOpts<PlatformAIModeResponse>) => {
  return useQuery<PlatformAIModeResponse>({
    queryKey: getGetPlatformAiModeQueryKey(),
    queryFn: () => getPlatformAiMode(),
    ...options,
  });
};

export const useUpdatePlatformAIMode = (
  options?: MutationOpts<PlatformAIModeResponse, PlatformAIModeUpdate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: PlatformAIModeUpdate) => updatePlatformAiMode(data),
    onSuccess: (...args) => {
      // A mode change flips every downstream surface (connections, resolved)
      // across the active community — flush the whole AI family.
      void invalidate(q.allAISettings());
      onSuccess?.(...args);
    },
  });
};

// ── Platform connections (personal / platform) ────────────────────────────────

export const usePlatformConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListPlatformConnectionsQueryKey(),
    queryFn: () => listPlatformConnections(),
    ...options,
  });
};

export const useCreatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) => createPlatformConnection(data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useUpdatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, { connectionId: number; data: AIConnectionUpdate }>
) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ connectionId, data }: { connectionId: number; data: AIConnectionUpdate }) =>
      updatePlatformConnection(connectionId, data),
    // Pending until the list has reloaded, so a row's switch holds the
    // value it asked for rather than showing the old one in between.
    onSuccess: async (...args) => {
      await invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useDeletePlatformConnection = (options?: MutationOpts<void, number>) => {
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (connectionId: number) => deletePlatformConnection(connectionId),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("platform");
      onSuccess?.(...args);
    },
  });
};

export const useTestPlatformConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) => {
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => testPlatformConnection(connectionId),
  });
};

export const useFetchPlatformConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchPlatformConnectionModels(connectionId),
  });
};

// ── Community connections (community-scoped) ──────────────────────────────────────────

export const useCommunityConnections = (options?: QueryOpts<AIConnectionResponse[]>) => {
  const communityId = useActiveCommunityId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<AIConnectionResponse[]>({
    queryKey: getListCommunityConnectionsQueryKey(communityId),
    queryFn: () => listCommunityConnections(communityId),
    enabled: userEnabled && communityId > 0,
    ...rest,
  });
};

export const useCreateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (data: AIConnectionCreate) => createCommunityConnection(communityId, data),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useUpdateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, { connectionId: number; data: AIConnectionUpdate }>
) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: ({ connectionId, data }: { connectionId: number; data: AIConnectionUpdate }) =>
      updateCommunityConnection(communityId, connectionId, data),
    // Pending until the list has reloaded, so a row's switch holds the
    // value it asked for rather than showing the old one in between.
    onSuccess: async (...args) => {
      await invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useDeleteCommunityConnection = (options?: MutationOpts<void, number>) => {
  const communityId = useActiveCommunityId();
  const { onSuccess, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: (connectionId: number) => deleteCommunityConnection(communityId, connectionId),
    onSuccess: (...args) => {
      void invalidateConnectionSurfaces("community");
      onSuccess?.(...args);
    },
  });
};

export const useTestCommunityConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) => {
  const communityId = useActiveCommunityId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => testCommunityConnection(communityId, connectionId),
  });
};

export const useFetchCommunityConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  const communityId = useActiveCommunityId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchCommunityConnectionModels(communityId, connectionId),
  });
};
