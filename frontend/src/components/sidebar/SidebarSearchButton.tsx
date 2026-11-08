import { Search } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { getOpenCommandCenter } from "@/components/search/CommandCenter";

interface SidebarSearchButtonProps {
  /** Name of the community being searched; shown in the placeholder. */
  communityName?: string | null;
}

/**
 * Full-bleed search row under the community name that opens the command
 * center. It spans the sidebar edge to edge, so it carries no border or
 * rounding of its own beyond the rule separating it from what follows. The
 * command palette is still reachable with ctrl/cmd-K, which the trailing hint
 * spells out.
 */
export const SidebarSearchButton = ({ communityName }: SidebarSearchButtonProps) => {
  const { t } = useTranslation(["search", "command"]);

  const shortcutLabel = useMemo(
    () =>
      typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent)
        ? "⌘K"
        : "Ctrl+K",
    []
  );

  // Same sentence the search page puts in its own input, from the same key.
  const label = communityName ? t("search:placeholder", { communityName }) : t("search:title");

  return (
    <button
      type="button"
      onClick={() => getOpenCommandCenter()?.()}
      aria-label={t("command:shortcutTooltip", { shortcut: shortcutLabel })}
      className="flex h-9 w-full min-w-0 items-center gap-2 border-b px-2.5 text-left text-muted-foreground text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      <Search className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <kbd className="pointer-events-none inline-flex shrink-0 select-none items-center rounded border bg-muted px-1.5 py-0.5 font-medium font-mono text-3xs text-muted-foreground">
        {shortcutLabel}
      </kbd>
    </button>
  );
};
