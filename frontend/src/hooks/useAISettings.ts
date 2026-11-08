import { useMutation } from "@tanstack/react-query";

import {
  createCommunityConnection,
  createPlatformConnection,
  deleteCommunityConnection,
  deletePlatformConnection,
  fetchCommunityConnectionModels,
  fetchPlatformConnectionModels,
  testCommunityConnection,
  testPlatformConnection,
  updateCommunityConnection,
  updatePlatformAiMode,
  updatePlatformConnection,
  useListCommunityConnections,
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
import { useApiMutation, useCommunityMutation } from "@/hooks/useApiMutation";
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

type ConnectionUpdateVars = { connectionId: number; data: AIConnectionUpdate };

// ── Platform mode (personal / platform) ───────────────────────────────────────

export const useUpdatePlatformAIMode = (
  options?: MutationOpts<PlatformAIModeResponse, PlatformAIModeUpdate>
) =>
  useApiMutation<PlatformAIModeResponse, PlatformAIModeUpdate>(
    {
      mutationFn: (data) => updatePlatformAiMode(data),
      // A mode change flips every downstream surface (connections, resolved)
      // across the active community — flush the whole AI family.
      invalidate: () => invalidate(q.allAISettings()),
      errorKey: "settings:platformAI.modeSaveError",
    },
    options
  );

// ── Platform connections (personal / platform) ────────────────────────────────

export const useCreatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) =>
  useApiMutation<AIConnectionResponse, AIConnectionCreate>(
    {
      mutationFn: (data) => createPlatformConnection(data),
      invalidate: () => invalidateConnectionSurfaces("platform"),
      errorKey: "settings:aiConnections.saveError",
    },
    options
  );

export const useUpdatePlatformConnection = (
  options?: MutationOpts<AIConnectionResponse, ConnectionUpdateVars>
) =>
  useApiMutation<AIConnectionResponse, ConnectionUpdateVars>(
    {
      mutationFn: ({ connectionId, data }) => updatePlatformConnection(connectionId, data),
      errorKey: "settings:aiConnections.saveError",
    },
    {
      ...options,
      // Pending until the list has reloaded, so a row's switch holds the
      // value it asked for rather than showing the old one in between.
      onSuccess: async (...args) => {
        await invalidateConnectionSurfaces("platform");
        return options?.onSuccess?.(...args);
      },
    }
  );

export const useDeletePlatformConnection = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (connectionId) => deletePlatformConnection(connectionId),
      invalidate: () => invalidateConnectionSurfaces("platform"),
      errorKey: "settings:aiConnections.deleteError",
    },
    options
  );

export const useTestPlatformConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) =>
  useApiMutation<AIConnectionTestResponse, number>(
    {
      mutationFn: (connectionId) => testPlatformConnection(connectionId),
      errorKey: "settings:ai.testError",
    },
    options
  );

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
  return useListCommunityConnections(communityId, {
    query: { enabled: userEnabled && communityId > 0, ...rest },
  });
};

export const useCreateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, AIConnectionCreate>
) =>
  useCommunityMutation<AIConnectionResponse, AIConnectionCreate>(
    {
      mutationFn: (communityId, data) => createCommunityConnection(communityId, data),
      invalidate: () => invalidateConnectionSurfaces("community"),
      errorKey: "settings:aiConnections.saveError",
    },
    options
  );

export const useUpdateCommunityConnection = (
  options?: MutationOpts<AIConnectionResponse, ConnectionUpdateVars>
) =>
  useCommunityMutation<AIConnectionResponse, ConnectionUpdateVars>(
    {
      mutationFn: (communityId, { connectionId, data }) =>
        updateCommunityConnection(communityId, connectionId, data),
      errorKey: "settings:aiConnections.saveError",
    },
    {
      ...options,
      // Pending until the list has reloaded, so a row's switch holds the
      // value it asked for rather than showing the old one in between.
      onSuccess: async (...args) => {
        await invalidateConnectionSurfaces("community");
        return options?.onSuccess?.(...args);
      },
    }
  );

export const useDeleteCommunityConnection = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, connectionId) =>
        deleteCommunityConnection(communityId, connectionId),
      invalidate: () => invalidateConnectionSurfaces("community"),
      errorKey: "settings:aiConnections.deleteError",
    },
    options
  );

export const useTestCommunityConnection = (
  options?: MutationOpts<AIConnectionTestResponse, number>
) =>
  useCommunityMutation<AIConnectionTestResponse, number>(
    {
      mutationFn: (communityId, connectionId) => testCommunityConnection(communityId, connectionId),
      errorKey: "settings:ai.testError",
    },
    options
  );

export const useFetchCommunityConnectionModels = (
  options?: MutationOpts<AIModelsResponse, number>
) => {
  const communityId = useActiveCommunityId();
  return useMutation({
    ...options,
    mutationFn: (connectionId: number) => fetchCommunityConnectionModels(communityId, connectionId),
  });
};
