import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  clearProviderDefault,
  createAuthProvider,
  deleteAuthProvider,
  discoverAuthProvider,
  getGetProviderDefaultQueryKey,
  setProviderDefault,
  testAuthProvider,
  updateAuthProvider,
  useGetProviderDefault,
  useListAuthProviders,
} from "@/api/generated/auth-providers/auth-providers";
import { useGetAppConfig } from "@/api/generated/config/config";
import type {
  AppConfig,
  AuthProviderCreate,
  AuthProviderOwnerRead,
  AuthProviderProbeResult,
  AuthProviderUpdate,
  CaptchaSettingsResponse,
  CaptchaSettingsUpdate,
  ChangelogResponse,
  CommunityNarrowingPending,
  CommunitySettingsResponse,
  CommunitySettingsUpdate,
  CommunitySuspensionUpdate,
  EmailSettingsResponse,
  EmailSettingsUpdate,
  GetChangelogParams,
  InterfaceSettingsResponse,
  InterfaceSettingsUpdate,
  ListPlatformCommunityStorageParams,
  NotificationSettingsResponse,
  NotificationSettingsUpdate,
  OIDCSettingsResponse,
  PlatformAuthSettingsResponse,
  PlatformAuthSettingsUpdate,
  PlatformCommunityRestore,
  PlatformCommunityStorageListResponse,
  PlatformCommunityStorageRead,
  PlatformCommunityStorageUpdate,
  PlatformProviderDefaultRead,
  PlatformProviderDefaultUpdate,
  PushSettingsResponse,
  PushSettingsUpdate,
  StorageBackfillStatusResponse,
  StorageSettingsResponse,
  StorageSettingsUpdate,
  StorageTestResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  agreeCommunityNarrowing,
  restorePlatformCommunity,
  sendTestEmail,
  setPlatformCommunitySuspension,
  startStorageBackfill,
  testStorageConnection,
  updateCaptchaSettings,
  updateCommunitySettings,
  updateEmailSettings,
  updateInterfaceSettings,
  updateNotificationSettings,
  updatePlatformAuthSettings,
  updatePlatformCommunityStorage,
  updatePushSettings,
  updateStorageSettings,
  useGetCaptchaSettings,
  useGetEmailSettings,
  useGetFcmConfig,
  useGetNotificationSettings,
  useGetOidcSettings,
  useGetPlatformAuthSettings,
  useGetPushSettings,
  useGetStorageBackfillStatus,
  useGetStorageSettings,
  useListPlatformCommunityStorage,
  useReadCommunityNarrowings,
  useReadCommunitySettings,
} from "@/api/generated/settings/settings";
import { useGetChangelog } from "@/api/generated/version/version";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

export const useOidcSettings = (options?: QueryOpts<OIDCSettingsResponse>) => {
  return useGetOidcSettings({ query: options });
};

export const useAuthProviders = (options?: QueryOpts<AuthProviderOwnerRead[]>) => {
  return useListAuthProviders({ query: options });
};

/** What a community says its own arrivals look like, for the operator. */
export const useCommunityNarrowings = (
  communityId: number,
  options?: QueryOpts<CommunityNarrowingPending[]>
) => {
  return useReadCommunityNarrowings(communityId, { query: options });
};

/** Agree that a community's claim values are its own, or withdraw that. */
export const useAgreeCommunityNarrowing = (
  communityId: number,
  options?: MutationOpts<CommunityNarrowingPending, { connectionId: number; agreed: boolean }>
) =>
  useApiMutation<CommunityNarrowingPending, { connectionId: number; agreed: boolean }>(
    {
      mutationFn: ({ connectionId, agreed }) =>
        agreeCommunityNarrowing(communityId, connectionId, { agreed }),
      invalidate: () => invalidate(q.communityNarrowings(communityId)),
    },
    options
  );

export const useEmailSettings = (options?: QueryOpts<EmailSettingsResponse>) => {
  return useGetEmailSettings({ query: options });
};

export const useStorageSettings = (options?: QueryOpts<StorageSettingsResponse>) => {
  return useGetStorageSettings({ query: options });
};

export const useStorageBackfillStatus = (options?: QueryOpts<StorageBackfillStatusResponse>) => {
  return useGetStorageBackfillStatus({ query: options });
};

export const useCaptchaSettings = (options?: QueryOpts<CaptchaSettingsResponse>) =>
  useGetCaptchaSettings({ query: options });

export const usePushSettings = (options?: QueryOpts<PushSettingsResponse>) =>
  useGetPushSettings({ query: options });

/** The branding page's values, read from the public config they live in. */
export const useInterfaceSettings = (options?: QueryOpts<AppConfig>) => {
  return useGetAppConfig({ query: options });
};

export const useFcmConfig = () => {
  return useGetFcmConfig(undefined, { query: { staleTime: 5 * 60 * 1000 } });
};

/**
 * One page of communities with their storage caps, for the operator dashboard →
 * Communities tab, searched and sorted on the server. Support and above
 * (`communities.read`); pass `{ enabled }` to skip the request for anyone else.
 * Each row carries what the reader may do to it, in `allowed_actions`.
 */
export const usePlatformCommunities = (
  params: ListPlatformCommunityStorageParams,
  options?: QueryOpts<PlatformCommunityStorageListResponse>
) => {
  return useListPlatformCommunityStorage(params, {
    query: { placeholderData: keepPreviousData, ...options },
  });
};

export const useChangelog = (
  params: GetChangelogParams,
  options?: QueryOpts<ChangelogResponse>
) => {
  return useGetChangelog(params, { query: options });
};

// ── Settings Mutations ──────────────────────────────────────────────────────

export const useCreateAuthProvider = (
  options?: MutationOpts<AuthProviderOwnerRead, AuthProviderCreate>
) =>
  useApiMutation<AuthProviderOwnerRead, AuthProviderCreate>(
    {
      mutationFn: (data) => createAuthProvider(data),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

export const useUpdateAuthProvider = (
  options?: MutationOpts<AuthProviderOwnerRead, { providerId: number; data: AuthProviderUpdate }>
) =>
  useApiMutation<AuthProviderOwnerRead, { providerId: number; data: AuthProviderUpdate }>(
    {
      mutationFn: ({ providerId, data }) => updateAuthProvider(providerId, data),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

export const useDeleteAuthProvider = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (providerId) => deleteAuthProvider(providerId),
      invalidate: () => invalidate(q.authProviders()),
    },
    options
  );

/** Look up an address somebody is still typing. Nothing is saved, and nothing
 *  in the cache changes, so there is nothing to invalidate. */
export const useDiscoverAuthProvider = (
  options?: MutationOpts<AuthProviderProbeResult, { issuer: string }>
) =>
  useApiMutation<AuthProviderProbeResult, { issuer: string }>(
    { mutationFn: (data) => discoverAuthProvider(data) },
    options
  );

/** Look up a saved provider, against the address on its row. */
export const useTestAuthProvider = (options?: MutationOpts<AuthProviderProbeResult, number>) =>
  useApiMutation<AuthProviderProbeResult, number>(
    {
      mutationFn: (providerId) => testAuthProvider(providerId),
    },
    options
  );

export const useUpdateInterfaceSettings = (
  options?: MutationOpts<InterfaceSettingsResponse, InterfaceSettingsUpdate>
) =>
  useApiMutation<InterfaceSettingsResponse, InterfaceSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateInterfaceSettings(data as Parameters<typeof updateInterfaceSettings>[0]),
      // The cookie-notice switch shares this endpoint and is also on the boot
      // config, which is where the notice itself reads it.
      invalidate: () => invalidate(q.appConfig()),
    },
    options
  );

/**
 * The three community-wide decisions, for the owner's settings page.
 *
 * The two switches are on the boot config, which is where every other page
 * reads them; the default direct-message policy is not, because nothing in the
 * SPA acts on it — the server applies it when an account is made. So it is
 * read here, behind the capability that writes it.
 */
export const useCommunitySettings = () => useReadCommunitySettings();

/**
 * Turn the community directory on or off for the whole deployment (owner only).
 *
 * Invalidates the boot config, which carries the two switches every signed-in
 * page reads, and this page's own read, which carries the third decision.
 */
export const useUpdateCommunitySettings = (
  options?: MutationOpts<CommunitySettingsResponse, CommunitySettingsUpdate>
) =>
  useApiMutation<CommunitySettingsResponse, CommunitySettingsUpdate>(
    {
      mutationFn: (data) =>
        updateCommunitySettings(data as Parameters<typeof updateCommunitySettings>[0]),
      invalidate: () => invalidate(q.appConfig(), q.communitySettings()),
    },
    options
  );

/**
 * Where sign-in is configured, which ways in are permitted, and what changing
 * either would cost. Owner only.
 */
/**
 * What this deployment permits a notification to leave the app carrying, and
 * how many device tokens switching push off would drop.
 */
export const useNotificationSettings = (options?: QueryOpts<NotificationSettingsResponse>) =>
  useGetNotificationSettings({ query: options });

/**
 * Set the three answers. Switching push off also drops the device tokens the
 * deployment was holding, so the count the page shows moves with the write.
 */
export const useUpdateNotificationSettings = (
  options?: MutationOpts<NotificationSettingsResponse, NotificationSettingsUpdate>
) =>
  useApiMutation<NotificationSettingsResponse, NotificationSettingsUpdate>(
    {
      mutationFn: (data) => updateNotificationSettings(data),
      invalidate: () => invalidate(q.notificationSettings()),
    },
    options
  );

export const usePlatformAuthSettings = (options?: QueryOpts<PlatformAuthSettingsResponse>) =>
  useGetPlatformAuthSettings({ query: options });

/**
 * Change any of the deployment's sign-in rules: which ways in it permits, who
 * it asks for a second factor, and how long a session may last.
 *
 * Also invalidates the boot config: the login page reads the permitted methods
 * from there to decide whether to offer the password form.
 */
export const useUpdatePlatformAuthSettings = (
  options?: MutationOpts<PlatformAuthSettingsResponse, PlatformAuthSettingsUpdate>
) =>
  useApiMutation<PlatformAuthSettingsResponse, PlatformAuthSettingsUpdate>(
    {
      mutationFn: (data) => updatePlatformAuthSettings(data),
      invalidate: () => invalidate(q.platformAuthSettings(), q.authSettings(), q.appConfig()),
    },
    options
  );

/**
 * Set the registration captcha. Also invalidates the boot config, which is
 * where the sign-up page reads the provider and site key from.
 */
export const useUpdateCaptchaSettings = (
  options?: MutationOpts<CaptchaSettingsResponse, CaptchaSettingsUpdate>
) =>
  useApiMutation<CaptchaSettingsResponse, CaptchaSettingsUpdate>(
    {
      mutationFn: (data) => updateCaptchaSettings(data),
      invalidate: () => invalidate(q.captchaSettings(), q.appConfig()),
    },
    options
  );

/**
 * Set the Firebase connection. Also invalidates the public half the app reads
 * when it registers for push.
 */
export const useUpdatePushSettings = (
  options?: MutationOpts<PushSettingsResponse, PushSettingsUpdate>
) =>
  useApiMutation<PushSettingsResponse, PushSettingsUpdate>(
    {
      mutationFn: (data) => updatePushSettings(data),
      invalidate: () => invalidate(q.pushSettings(), q.fcmConfig()),
    },
    options
  );

export const useUpdateEmailSettings = (
  options?: MutationOpts<EmailSettingsResponse, EmailSettingsUpdate>
) =>
  useApiMutation<EmailSettingsResponse, EmailSettingsUpdate>(
    {
      mutationFn: (data) => updateEmailSettings(data as Parameters<typeof updateEmailSettings>[0]),
      invalidate: () => invalidate(q.emailSettings()),
    },
    options
  );

export const useSendTestEmail = (
  options?: MutationOpts<void, Parameters<typeof sendTestEmail>[0]>
) =>
  useApiMutation<void, Parameters<typeof sendTestEmail>[0]>(
    {
      mutationFn: async (data) => {
        await sendTestEmail(data);
      },
    },
    options
  );

export const useUpdateStorageSettings = (
  options?: MutationOpts<StorageSettingsResponse, StorageSettingsUpdate>
) =>
  useApiMutation<StorageSettingsResponse, StorageSettingsUpdate>(
    {
      mutationFn: (data) =>
        updateStorageSettings(data as Parameters<typeof updateStorageSettings>[0]),
      invalidate: () => invalidate(q.storageSettings()),
    },
    options
  );

export const useTestStorageConnection = (
  options?: MutationOpts<StorageTestResponse, StorageSettingsUpdate>
) =>
  useApiMutation<StorageTestResponse, StorageSettingsUpdate>(
    {
      mutationFn: (data) =>
        testStorageConnection(data as Parameters<typeof testStorageConnection>[0]),
    },
    options
  );

export const useStartStorageBackfill = (
  options?: MutationOpts<StorageBackfillStatusResponse, void>
) =>
  useApiMutation<StorageBackfillStatusResponse, void>(
    {
      mutationFn: () => startStorageBackfill(),
    },
    options
  );

export const useRestoreCommunity = (
  options?: MutationOpts<
    PlatformCommunityStorageRead,
    { communityId: number; data: PlatformCommunityRestore }
  >
) =>
  useApiMutation<
    PlatformCommunityStorageRead,
    { communityId: number; data: PlatformCommunityRestore }
  >(
    {
      mutationFn: ({ communityId, data }) => restorePlatformCommunity(communityId, data),
      invalidate: () => invalidate(q.platformCommunities()),
    },
    options
  );

export const useUpdateCommunityStorage = (
  options?: MutationOpts<
    PlatformCommunityStorageRead,
    { communityId: number; data: PlatformCommunityStorageUpdate }
  >
) =>
  useApiMutation<
    PlatformCommunityStorageRead,
    { communityId: number; data: PlatformCommunityStorageUpdate }
  >(
    {
      mutationFn: ({ communityId, data }) =>
        updatePlatformCommunityStorage(
          communityId,
          data as Parameters<typeof updatePlatformCommunityStorage>[1]
        ),
      // The help-request switch decides what "Ask for help" offers.
      invalidate: () => invalidate(q.platformCommunities(), q.ticketAvailability()),
    },
    options
  );

/**
 * Suspend a community, or lift its suspension (``communities.suspend``, under a
 * live ``moderate`` grant on it). Lifting returns it to the row's `lifts_to`.
 */
export const useSetCommunitySuspension = (
  options?: MutationOpts<
    PlatformCommunityStorageRead,
    { communityId: number; data: CommunitySuspensionUpdate }
  >
) =>
  useApiMutation<
    PlatformCommunityStorageRead,
    { communityId: number; data: CommunitySuspensionUpdate }
  >(
    {
      mutationFn: ({ communityId, data }) => setPlatformCommunitySuspension(communityId, data),
      invalidate: () => invalidate(q.platformCommunities()),
    },
    options
  );

/** The deployment's own answer for one provider, for communities that have
 *  not made their own arrangement. Null where it has made none. */
export const useProviderDefault = (
  providerId: number | null,
  options?: QueryOpts<PlatformProviderDefaultRead | null>
) => {
  return useGetProviderDefault(providerId as number, {
    query: { enabled: providerId !== null, ...options },
  });
};

const useInvalidateProviderDefault = (providerId: number) => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getGetProviderDefaultQueryKey(providerId),
    });
  };
};

export const useSetProviderDefault = (providerId: number) => {
  const invalidate = useInvalidateProviderDefault(providerId);
  return useMutation({
    mutationFn: (data: PlatformProviderDefaultUpdate) => setProviderDefault(providerId, data),
    onSuccess: invalidate,
  });
};

export const useClearProviderDefault = (providerId: number) => {
  const invalidate = useInvalidateProviderDefault(providerId);
  return useMutation({
    mutationFn: () => clearProviderDefault(providerId),
    onSuccess: invalidate,
  });
};
