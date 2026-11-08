import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagTreeView, UNTAGGED_PATH } from "@/components/tags/TagTreeView";
import { getContrastingTextColor } from "@/lib/counter-color";
import { cn } from "@/ui/lib/utils";

interface TagBrowseLayoutProps {
  allTags: TagSummary[];
  tagCounts: Record<number, number>;
  /** Offers "Not tagged"; left off where the list cannot be narrowed to it. */
  untaggedCount?: number | null;
  selectedPaths: Set<string>;
  onToggleTag: (fullPath: string, ctrlKey: boolean) => void;
  /** What the picked tags narrow: the tool's own cards. */
  children: ReactNode;
}

/**
 * A list browsed by tag: the tag tree beside it on a wide screen, a row of tag
 * chips above it on a phone. Every tool's tags view is this around its own
 * cards.
 */
export const TagBrowseLayout = ({
  allTags,
  tagCounts,
  untaggedCount,
  selectedPaths,
  onToggleTag,
  children,
}: TagBrowseLayoutProps) => {
  const { t } = useTranslation("tags");
  const chipTags = [...allTags]
    .filter((tag) => (tagCounts[tag.id] ?? 0) > 0 || selectedPaths.has(tag.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  const tree = (
    <TagTreeView
      tags={allTags}
      tagCounts={tagCounts}
      untaggedCount={untaggedCount}
      selectedTagPaths={selectedPaths}
      // Every click adds or drops a tag, as a chip does on a phone.
      onToggleTag={(path) => onToggleTag(path, true)}
    />
  );

  return (
    <div className="flex canvas-sm:flex-row flex-col gap-4">
      {/* On a phone, the tags themselves in a row that scrolls sideways: one
          tap picks or drops a tag, and several can be picked. A tag nothing here carries is
          left out, so the row is only as long as it is useful. */}
      <div className="-mx-4 flex canvas-sm:hidden gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {chipTags.map((tag) => {
          const selected = selectedPaths.has(tag.name);
          return (
            <button
              key={tag.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onToggleTag(tag.name, true)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 font-medium text-xs transition",
                selected
                  ? "ring-2 ring-foreground ring-offset-1 ring-offset-background"
                  : "opacity-90"
              )}
              style={{
                backgroundColor: tag.color,
                color: getContrastingTextColor(tag.color),
              }}
            >
              {selected ? <Check className="h-3 w-3" aria-hidden /> : null}
              {tag.name}
              <span className="tabular-nums opacity-75">{tagCounts[tag.id] ?? 0}</span>
            </button>
          );
        })}
        {untaggedCount != null ? (
          <button
            type="button"
            aria-pressed={selectedPaths.has(UNTAGGED_PATH)}
            onClick={() => onToggleTag(UNTAGGED_PATH, true)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-md border border-dashed px-2 py-1 font-medium text-xs transition-colors",
              selectedPaths.has(UNTAGGED_PATH) ? "bg-accent" : "bg-background hover:bg-accent"
            )}
          >
            {t("tree.notTagged")}
            <span className="tabular-nums opacity-70">{untaggedCount}</span>
          </button>
        ) : null}
      </div>
      <div className="canvas-sm:block hidden w-64 shrink-0 rounded-md border border-muted bg-background/40">
        {tree}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
};
