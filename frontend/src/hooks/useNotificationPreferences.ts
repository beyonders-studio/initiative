import { useQueryClient } from "@tanstack/react-query";

import type {
  NotificationPreferencesRead,
  NotificationPreferencesUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getReadMyNotificationPreferencesQueryKey,
  updateMyNotificationPreferences,
} from "@/api/generated/notifications/notifications";
import { useApiMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * Move some switches.
 *
 * A partial write — one switch is one request — so two open settings tabs
 * cannot overwrite each other's unrelated rows. The response is the whole
 * settled document, which is what the cache takes.
 */
export const useUpdateNotificationPreferences = (
  options?: MutationOpts<NotificationPreferencesRead, NotificationPreferencesUpdate>
) => {
  const client = useQueryClient();
  return useApiMutation<NotificationPreferencesRead, NotificationPreferencesUpdate>(
    {
      mutationFn: (payload) => updateMyNotificationPreferences(payload),
    },
    {
      ...options,
      onSuccess: (...args) => {
        const [settled] = args;
        // The server answered with the whole document, so there is nothing to
        // refetch — writing it straight in keeps the grid from flickering back
        // through a loading state on every switch.
        client.setQueryData(getReadMyNotificationPreferencesQueryKey(), settled);
        options?.onSuccess?.(...args);
      },
    }
  );
};
