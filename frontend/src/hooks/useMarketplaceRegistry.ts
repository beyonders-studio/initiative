/**
 * The marketplace registry, as the platform owner manages it: whether this
 * server follows it, how the last refresh went, "refresh now", and uploading a
 * registry bundle for a server that cannot reach it.
 *
 * Every write changes what the catalog holds, so each one refreshes the status
 * and every community's marketplace listings.
 */

import { type QueryClient, useQueryClient } from "@tanstack/react-query";

import type { RegistryRefreshRead, RegistrySettings } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadRegistryStatusQueryKey,
  refreshRegistryNow,
  updateRegistrySettings,
  uploadRegistryBundle,
} from "@/api/generated/marketplace/marketplace";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

const invalidateRegistry = (queryClient: QueryClient) => {
  void queryClient.invalidateQueries({
    queryKey: getReadRegistryStatusQueryKey(),
  });
  // The shelf is keyed per community, so every community's copy is dropped.
  void queryClient.invalidateQueries({
    predicate: (query) =>
      typeof query.queryKey[0] === "string" && query.queryKey[0].includes("/marketplace/"),
  });
};

export const useUpdateRegistrySettings = (
  options?: MutationOpts<RegistrySettings, RegistrySettings>
) => {
  const queryClient = useQueryClient();
  return useApiMutation<RegistrySettings, RegistrySettings>(
    {
      mutationFn: (data) => updateRegistrySettings(data),
      invalidate: () => invalidateRegistry(queryClient),
      errorKey: "settings:marketplaceRegistry.saveError",
    },
    options
  );
};

export const useRefreshRegistry = (options?: MutationOpts<RegistryRefreshRead, void>) => {
  const queryClient = useQueryClient();
  return useApiMutation<RegistryRefreshRead, void>(
    {
      mutationFn: () => refreshRegistryNow(),
      invalidate: () => invalidateRegistry(queryClient),
      errorKey: "settings:marketplaceRegistry.refreshError",
    },
    {
      ...options,
      // A refusal is recorded on the status too, so it is refetched either way.
      onError: (...args) => {
        invalidateRegistry(queryClient);
        options?.onError?.(...args);
      },
    }
  );
};

export const useUploadRegistryBundle = (options?: MutationOpts<RegistryRefreshRead, File>) => {
  const queryClient = useQueryClient();
  return useApiMutation<RegistryRefreshRead, File>(
    {
      mutationFn: (file) => uploadRegistryBundle({ file }),
      invalidate: () => invalidateRegistry(queryClient),
      errorKey: "settings:marketplaceRegistry.bundleError",
    },
    {
      ...options,
      onError: (...args) => {
        invalidateRegistry(queryClient);
        options?.onError?.(...args);
      },
    }
  );
};
