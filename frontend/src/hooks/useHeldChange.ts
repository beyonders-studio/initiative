import { useTranslation } from "react-i18next";

import type { HeldChangeRead } from "@/api/generated/initiativeAPI.schemas";
import {
  applyHeldChange,
  cancelHeldChange,
  getReadHeldChangeQueryKey,
} from "@/api/generated/users/users";
import { useApiMutation } from "@/hooks/useApiMutation";
import { toast } from "@/lib/mascotToast";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import { formatDateTime } from "@/ui/lib/formatDate";

export const HELD_CHANGE_QUERY_KEY = getReadHeldChangeQueryKey();

const refresh = () => queryClient.invalidateQueries({ queryKey: HELD_CHANGE_QUERY_KEY });

/**
 * Whether a change came back waiting rather than made: the routes that can
 * hold one answer with it in place of their usual body.
 */
export const isHeld = (result: unknown): result is HeldChangeRead =>
  typeof result === "object" && result !== null && "applies_at" in result;

/** Says when a change that came back waiting will be made, and shows it. */
export const useAnnounceHeld = () => {
  const { t } = useTranslation("settings");
  return (held: HeldChangeRead) => {
    toast.info(t("heldChange.waits", { date: formatDateTime(held.applies_at) }));
    void refresh();
  };
};

export const useCancelHeldChange = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (id) => cancelHeldChange(id),
      invalidate: refresh,
      errorKey: "settings:heldChange.cancelFailed",
    },
    options
  );

/**
 * Make the waiting change now. The session has to have been proved with a
 * passkey, which the passkey step-up gives. What it changes can be on any
 * settings page, so everything is read again.
 */
export const useApplyHeldChange = (options?: MutationOpts<void, number>) =>
  useApiMutation<void, number>(
    {
      mutationFn: (id) => applyHeldChange(id),
      invalidate: () => queryClient.invalidateQueries(),
      errorKey: "settings:heldChange.applyFailed",
    },
    options
  );
