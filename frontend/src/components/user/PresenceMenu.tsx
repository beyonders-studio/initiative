import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Presence } from "@/api/generated/initiativeAPI.schemas";
import { PresenceMenuItems } from "@/components/user/PresenceMenuItems";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

interface PresenceMenuProps {
  /** What the account is set to — the choice, not what a reader is shown. */
  presence: Presence;
  /** The control this hangs off: the dot beside your picture. */
  children: ReactNode;
  align?: "start" | "center" | "end";
  side?: "top" | "right" | "bottom" | "left";
  /** Re-read the account once the new choice is saved. */
  onChanged?: () => Promise<void> | void;
}

/**
 * The presence choices as a menu of their own, for the dot on the profile card
 * — where you are looking straight at the dot when you decide it is wrong.
 *
 * The sidebar reaches the same choices as a submenu of the account menu, so
 * both places offer one list and one setting.
 */
export const PresenceMenu = ({
  presence,
  children,
  align = "start",
  side,
  onChanged,
}: PresenceMenuProps) => {
  const { t } = useTranslation("profiles");

  return (
    // modal={false}: a modal dropdown nested in the non-modal mobile sidebar
    // drawer dismisses the drawer on open.
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} side={side} className="w-60">
        <DropdownMenuLabel>{t("presence.edit")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <PresenceMenuItems presence={presence} onChanged={onChanged} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
