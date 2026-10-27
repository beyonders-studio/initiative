import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { CollectionFileSummary, FileSummary } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";
import type { CollectionCard } from "@/components/files/collections/collectionLists";
import { type MasonryEntry, MasonryWall } from "@/components/files/collections/MasonryWall";
import { TagBadge } from "@/components/tags/TagBadge";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { useWidthClass } from "@/hooks/useWidthClass";
import { fileRatio, groupByTag } from "@/lib/collections";

interface CollectionMasonryViewProps {
  files: CollectionFileSummary[];
  /** What each file shows under its picture, as the layout says. */
  card?: CollectionCard;
  groupByTags: boolean;
  onActivate: (file: FileSummary, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (file: FileSummary) => boolean;
}

/** The narrowest a column gets before the wall drops one. Narrower on a phone,
 *  where two or three columns of files is the point and one is a list. */
const COLUMN_WIDTH = 220;
const COLUMN_WIDTH_COMPACT = 150;

/**
 * The wall: files at their own shapes, packed into columns, each placed where
 * the shortest column ends. A file whose size is not known stands at the
 * wall's one shape.
 *
 * Grouped by tag, it is one wall per tag with the untagged last — a file
 * carrying two tags stands on both walls, which is what "everything still
 * awaiting a decision" asks for.
 */
export const CollectionMasonryView = ({
  files,
  card,
  groupByTags,
  onActivate,
  selecting = false,
  isSelected,
}: CollectionMasonryViewProps) => {
  const { t } = useTranslation("files");
  const compact = useWidthClass() === "base";
  const minColumnWidth = compact ? COLUMN_WIDTH_COMPACT : COLUMN_WIDTH;

  const entriesOf = (items: CollectionFileSummary[]): MasonryEntry[] =>
    items.map((file) => ({
      key: file.id,
      aspectRatio: fileRatio(file),
      below: card?.height(file),
      render: () => (
        <>
          <CollectionFileTile
            file={file}
            onActivate={(options) => onActivate(file, options)}
            selecting={selecting}
            selected={isSelected?.(file) ?? false}
            named={card?.names}
            fit="shape"
          />
          {card?.render(file)}
        </>
      ),
    }));

  const sections = useMemo(
    () => (groupByTags ? groupByTag(files) : [{ tag: null, items: files }]),
    [files, groupByTags]
  );

  if (!groupByTags) {
    return <MasonryWall entries={entriesOf(files)} minColumnWidth={minColumnWidth} />;
  }

  return (
    <div className="space-y-8">
      {sections.map((group) => (
        <section key={group.tag?.id ?? "untagged"} className="space-y-3">
          <h3 className="flex items-center gap-2 font-medium text-sm">
            {group.tag ? (
              <TagBadge tag={group.tag} size="sm" />
            ) : (
              <span className="text-muted-foreground">{t("collections.groups.untagged")}</span>
            )}
            <span className="text-muted-foreground text-xs">
              {t("collections.groups.count", { count: group.items.length })}
            </span>
          </h3>
          <MasonryWall entries={entriesOf(group.items)} minColumnWidth={minColumnWidth} />
        </section>
      ))}
    </div>
  );
};
