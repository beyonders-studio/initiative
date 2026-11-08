import type {
  PluginServicePublishedKey,
  PluginServiceRegistrationCreate,
  PluginServiceRegistrationRead,
  PluginServiceRegistrationUpdate,
  PluginServiceVendorSetup,
} from "@/api/generated/initiativeAPI.schemas";
import {
  completePluginServiceVendorSetup,
  connectPluginService,
  createPluginService,
  deletePluginService,
  readPluginServiceKeys,
  startPluginServiceVendorSetup,
  updatePluginService,
  useListPluginServices,
} from "@/api/generated/plugin-services/plugin-services";
import { invalidate, q } from "@/api/query-keys";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

/** Every plug-in service this deployment has wired up (`plugins.manage`). */
export const usePluginServices = (options?: QueryOpts<PluginServiceRegistrationRead[]>) =>
  useListPluginServices({ query: options });

export const useCreatePluginService = (
  options?: MutationOpts<PluginServiceRegistrationRead, PluginServiceRegistrationCreate>
) =>
  useApiMutation<PluginServiceRegistrationRead, PluginServiceRegistrationCreate>(
    {
      mutationFn: (data) => createPluginService(data),
      invalidate: () => invalidate(q.pluginServices()),
    },
    options
  );

export interface UpdatePluginServiceVariables {
  registrationId: number;
  data: PluginServiceRegistrationUpdate;
}

export const useUpdatePluginService = (
  options?: MutationOpts<PluginServiceRegistrationRead, UpdatePluginServiceVariables>
) =>
  useApiMutation<PluginServiceRegistrationRead, UpdatePluginServiceVariables>(
    {
      mutationFn: ({ registrationId, data }) => updatePluginService(registrationId, data),
      invalidate: () => invalidate(q.pluginServices()),
    },
    options
  );

export const useDeletePluginService = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (registrationId) => deletePluginService(registrationId),
      invalidate: () => invalidate(q.pluginServices()),
    },
    options
  );

/**
 * Read the keys a plug-in serves at its base URL, each with its fingerprint. A
 * mutation because it runs when the operator presses Connect, and stores
 * nothing.
 */
export const usePluginServiceKeys = (options?: MutationOpts<PluginServicePublishedKey[], number>) =>
  useApiMutation<PluginServicePublishedKey[], number>(
    {
      mutationFn: (registrationId) => readPluginServiceKeys(registrationId),
    },
    options
  );

export interface ConnectPluginServiceVariables {
  registrationId: number;
  /** The keys the operator was shown and confirmed, kid and fingerprint. */
  keys: PluginServicePublishedKey[];
}

/** Pin the key set the plug-in serves, when it still holds exactly the confirmed keys. */
export const useConnectPluginService = (
  options?: MutationOpts<PluginServiceRegistrationRead, ConnectPluginServiceVariables>
) =>
  useApiMutation<PluginServiceRegistrationRead, ConnectPluginServiceVariables>(
    {
      mutationFn: ({ registrationId, keys }) =>
        connectPluginService(registrationId, {
          keys,
        }),
      invalidate: () => invalidate(q.pluginServices()),
    },
    options
  );

export interface StartVendorSetupVariables {
  registrationId: number;
  /** The organization to own the vendor's new client, or "" for the operator's account. */
  organization: string;
}

/** Start the vendor's own setup of the plug-in's client: what the browser posts to it, and where. */
export const useStartVendorSetup = (
  options?: MutationOpts<PluginServiceVendorSetup, StartVendorSetupVariables>
) =>
  useApiMutation<PluginServiceVendorSetup, StartVendorSetupVariables>(
    {
      mutationFn: ({ registrationId, organization }) =>
        startPluginServiceVendorSetup(registrationId, {
          organization: organization || null,
        }),
    },
    options
  );

export interface CompleteVendorSetupVariables {
  registrationId: number;
  code: string;
  state: string;
}

/** Finish the setup the vendor sent the operator back from, writing the vendor values. */
export const useCompleteVendorSetup = (
  options?: MutationOpts<PluginServiceRegistrationRead, CompleteVendorSetupVariables>
) =>
  useApiMutation<PluginServiceRegistrationRead, CompleteVendorSetupVariables>(
    {
      mutationFn: ({ registrationId, code, state }) =>
        completePluginServiceVendorSetup(registrationId, { code, state }),
      invalidate: () => invalidate(q.pluginServices()),
    },
    options
  );
