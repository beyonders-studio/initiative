import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Presence, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { PresenceDot } from "@/components/user/PresenceDot";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { PRESENCE_ORDER, presenceHelpKey, presenceLabelKey } from "@/lib/presence";
import { DropdownMenuItem } from "@/ui/dropdown-menu";

interface PresenceMenuItemsProps {
  /** What the account is set to — the choice, not what a reader is shown. */
  presence: Presence;
  /** Re-read the account once the new choice is saved. */
  onChanged?: () => Promise<void> | void;
}

/**
 * Picking how you appear: the choices on their own, to drop into a menu.
 *
 * Items rather than a menu of their own, because how you appear belongs beside
 * the rest of what you can say about yourself — it hangs off the account menu
 * in the sidebar, under the dot that is already showing the answer.
 *
 * Idle is offered even though it is also worked out on its own — a person who
 * would rather look like they stepped away can say so, and saying it means it
 * holds however busy their keyboard is.
 */
export const PresenceMenuItems = ({ presence, onChanged }: PresenceMenuItemsProps) => {
  const { t } = useTranslation("profiles");

  const save = useUpdateCurrentUser(
    {
      onSuccess: async () => {
        await onChanged?.();
      },
    },
    "profiles:presence.failed"
  );

  return (
    <>
      {PRESENCE_ORDER.map((option) => (
        <DropdownMenuItem
          key={option}
          className="items-start gap-2.5"
          disabled={save.isPending}
          onSelect={() => save.mutate({ presence: option } as UserSelfUpdate)}
        >
          <PresenceDot presence={option} className="mt-1 size-2.5 shrink-0" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="font-medium">{t(presenceLabelKey(option))}</span>
            <span className="text-muted-foreground text-xs">{t(presenceHelpKey(option))}</span>
          </span>
          {option === presence ? (
            <Check className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          ) : null}
        </DropdownMenuItem>
      ))}
    </>
  );
};
