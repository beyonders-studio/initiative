import {
  getListMySessionsQueryKey,
  revokeMyOtherSessions,
  revokeMySession,
  useListMySessions,
} from "@/api/generated/auth/auth";
import { removeDevice } from "@/api/generated/direct-messages/direct-messages";
import type {
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
  SignedInSessionInfo,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createMyApiKey,
  deleteMyApiKey,
  getListMyApiKeysQueryKey,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";

// ── Query Keys ──────────────────────────────────────────────────────────────

export const API_KEYS_QUERY_KEY = getListMyApiKeysQueryKey();
export const SESSIONS_QUERY_KEY = getListMySessionsQueryKey();

// ── Queries ─────────────────────────────────────────────────────────────────

export const useMySessions = () => useListMySessions();

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateApiKey = (
  options?: MutationOpts<ApiKeyCreateResponse, ApiKeyCreateRequest>,
  /** What a failure says. Omit where the caller reports it itself. */
  errorKey?: string
) =>
  useApiMutation<ApiKeyCreateResponse, ApiKeyCreateRequest>(
    {
      mutationFn: (data) => createMyApiKey(data),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
      errorKey,
    },
    options
  );

export const useDeleteApiKey = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (apiKeyId) => deleteMyApiKey(apiKeyId),
      invalidate: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
    },
    options
  );

/** End one row of the list: its sign-in, or a message device with none. */
export const useEndSignedIn = (options?: MutationOpts<void, SignedInSessionInfo>) =>
  useApiMutation<void, SignedInSessionInfo>(
    {
      mutationFn: (row) =>
        row.id ? revokeMySession(row.id) : removeDevice(row.message_device_id as string),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );

export const useRevokeOtherSessions = (options?: MutationOpts<void, void>) =>
  useApiMutation<void, void>(
    {
      mutationFn: () => revokeMyOtherSessions(),
      invalidate: () => queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY }),
    },
    options
  );
