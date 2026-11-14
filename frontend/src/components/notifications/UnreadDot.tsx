import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

/**
 * "Something here is unread."
 *
 * The same mark at every level of the navigation — community, initiative,
 * tool — so following it inward is one gesture repeated rather than three
 * different signals. Never a number: a count invites you to zero it, and three
 * levels deep it becomes arithmetic nobody asked for when the only question is
 * where to go.
 *
 * The community rail draws its own instead, sized and ringed like a presence
 * badge on the avatar; this is the inline mark for a row of text.
 */
export const UnreadDot = ({ className }: { className?: string }) => {
  const { t } = useTranslation("communities");
  return (
    <span
      role="img"
      aria-label={t("unreadHere")}
      title={t("unreadHere")}
      className={cn("size-2 shrink-0 rounded-full bg-primary", className)}
    />
  );
};
