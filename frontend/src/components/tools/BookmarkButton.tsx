import { Bookmark } from "lucide-react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useIsBookmarked, useToggleBookmark } from "@/hooks/usePersonalItems";
import { cn } from "@/ui/lib/utils";

interface BookmarkButtonProps {
  tool: Tool;
  entityId: number;
  /** What the sidebar shows for it until the server's answer arrives. */
  name?: string;
  initiativeId?: number | null;
  /** The tool's own community, where it is not the one the page is in. */
  communityId?: number;
  className?: string;
  /** On a card that is a link: the click bookmarks, and does not open the card. */
  suppressNavigation?: boolean;
  iconSize?: "sm" | "md";
}

/** The bookmark on any tool: on its page, its card and its row. */
export const BookmarkButton = ({
  tool,
  entityId,
  name,
  initiativeId,
  communityId,
  className,
  suppressNavigation = false,
  iconSize = "md",
}: BookmarkButtonProps) => {
  const { t } = useTranslation("common");
  const bookmarked = useIsBookmarked(tool, entityId, communityId);
  const toggle = useToggleBookmark();

  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (suppressNavigation) {
      event.preventDefault();
      event.stopPropagation();
    }
    toggle.mutate({ tool, entityId, next: !bookmarked, name, initiativeId, communityId });
  };

  return (
    <button
      type="button"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-amber-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default",
        iconSize === "sm" ? "size-7" : "size-9",
        className
      )}
      aria-pressed={bookmarked}
      aria-label={bookmarked ? t("bookmark.remove") : t("bookmark.add")}
      title={bookmarked ? t("bookmark.remove") : t("bookmark.add")}
      // One write at a time, so the last click is the one that holds.
      disabled={toggle.isPending}
      onClick={handleClick}
    >
      <Bookmark
        className={cn("size-4", bookmarked && "text-amber-500")}
        fill={bookmarked ? "currentColor" : "none"}
        aria-hidden
      />
    </button>
  );
};
