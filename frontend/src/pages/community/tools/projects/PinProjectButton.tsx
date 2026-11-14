import { Pin } from "lucide-react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import { useToggleProjectPin } from "@/hooks/useProjects";
import { cn } from "@/ui/lib/utils";

interface PinProjectButtonProps {
  projectId: number;
  isPinned: boolean;
  canPin: boolean;
  className?: string;
  suppressNavigation?: boolean;
  iconSize?: "sm" | "md";
}

const PinGlyph = ({ isPinned }: { isPinned: boolean }) => (
  <Pin
    className={cn("h-4 w-4", isPinned ? "text-primary" : undefined)}
    fill={isPinned ? "currentColor" : "none"}
  />
);

export const PinProjectButton = ({
  projectId,
  isPinned,
  canPin,
  className,
  suppressNavigation = false,
  iconSize = "md",
}: PinProjectButtonProps) => {
  const { t } = useTranslation("projects");
  const pinMutation = useToggleProjectPin();
  const pending = pinMutation.isPending && pinMutation.variables?.projectId === projectId;
  const sizeClasses = iconSize === "sm" ? "h-7 w-7" : "h-9 w-9";
  const baseClasses =
    "text-muted-foreground hover:bg-accent focus-visible:ring-ring inline-flex items-center justify-center rounded-md transition focus-visible:ring-2 focus-visible:outline-none";

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (!canPin) {
      return;
    }
    if (suppressNavigation) {
      event.preventDefault();
      event.stopPropagation();
    }
    pinMutation.mutate({ projectId, nextState: !isPinned });
  };

  // Hide completely if user can't pin and project isn't pinned
  // Show read-only indicator only if project is pinned
  if (!canPin) {
    if (!isPinned) {
      return null;
    }
    return (
      <div
        className={cn(baseClasses, sizeClasses, "cursor-default", className)}
        role="img"
        aria-label={t("pin.pinned")}
        title={t("pin.pinned")}
      >
        <PinGlyph isPinned={isPinned} />
      </div>
    );
  }

  return (
    <button
      type="button"
      className={cn(baseClasses, sizeClasses, "hover:text-primary disabled:opacity-60", className)}
      aria-pressed={isPinned}
      aria-label={isPinned ? t("pin.unpin") : t("pin.pin")}
      disabled={pending}
      onClick={handleClick}
    >
      <PinGlyph isPinned={isPinned} />
    </button>
  );
};
