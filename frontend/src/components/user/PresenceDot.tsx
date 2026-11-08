import { useTranslation } from "react-i18next";

import type { Presence } from "@/api/generated/initiativeAPI.schemas";
import { PRESENCE_COLOR, presenceLabelKey } from "@/lib/presence";
import { cn } from "@/ui/lib/utils";

interface PresenceDotProps {
  presence: Presence;
  /**
   * Say the state in words for a reader who cannot see the colour. Left off
   * where something around the dot already says it — a label beside it, or a
   * button holding it — so it is not read twice.
   */
  labelled?: boolean;
  className?: string;
}

/**
 * The coloured circle that says how someone is appearing.
 *
 * Sized by whatever contains it, so the same component is the quarter-sized
 * badge on an avatar and the small mark in a line of text.
 */
export const PresenceDot = ({ presence, labelled, className }: PresenceDotProps) => {
  const { t } = useTranslation("profiles");
  const label = t(presenceLabelKey(presence));

  return (
    <span
      role="img"
      className={cn("block rounded-full", PRESENCE_COLOR[presence], className)}
      aria-label={label}
      aria-hidden={labelled ? undefined : "true"}
      title={labelled ? label : undefined}
    />
  );
};
