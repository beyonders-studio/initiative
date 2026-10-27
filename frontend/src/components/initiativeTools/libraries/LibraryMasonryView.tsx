import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { LibraryItemRead } from "@/api/generated/initiativeAPI.schemas";
import { LibraryItemTile } from "@/components/initiativeTools/libraries/LibraryItemTile";
import { type MasonryEntry, MasonryWall } from "@/components/initiativeTools/libraries/MasonryWall";
import { TagBadge } from "@/components/tags/TagBadge";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { useWidthClass } from "@/hooks/useWidthClass";
import { aspectRatio, groupByTag } from "@/lib/libraries";

interface LibraryMasonryViewProps {
  images: LibraryItemRead[];
  groupByTags: boolean;
  onActivate: (image: LibraryItemRead, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (image: LibraryItemRead) => boolean;
}

/** The narrowest a column gets before the wall drops one. Narrower on a phone,
 *  where two or three columns of pictures is the point and one is a list. */
const COLUMN_WIDTH = 220;
const COLUMN_WIDTH_COMPACT = 150;

/** What the wall assumes a picture is until the server has said: a landscape
 *  it can reserve space for. Only ever stands in for a picture that could not
 *  be measured at upload. */
const FALLBACK_RATIO = 4 / 3;

/**
 * The wall: pictures at their own shapes, packed into columns.
 *
 * Grouped by tag, it is one wall per tag with the untagged last — a picture
 * carrying two tags stands on both walls, which is what "everything still
 * awaiting a decision" asks for.
 */
export const LibraryMasonryView = ({
  images,
  groupByTags,
  onActivate,
  selecting = false,
  isSelected,
}: LibraryMasonryViewProps) => {
  const { t } = useTranslation("libraries");
  const compact = useWidthClass() === "base";
  const minColumnWidth = compact ? COLUMN_WIDTH_COMPACT : COLUMN_WIDTH;

  const entriesOf = (items: LibraryItemRead[]): MasonryEntry[] =>
    items.map((image) => ({
      key: image.id,
      aspectRatio: aspectRatio(image) ?? FALLBACK_RATIO,
      render: () => (
        <LibraryItemTile
          image={image}
          onActivate={(options) => onActivate(image, options)}
          selecting={selecting}
          selected={isSelected?.(image) ?? false}
          fit="shape"
        />
      ),
    }));

  const sections = useMemo(
    () => (groupByTags ? groupByTag(images) : [{ tag: null, items: images }]),
    [images, groupByTags]
  );

  if (!groupByTags) {
    return <MasonryWall entries={entriesOf(images)} minColumnWidth={minColumnWidth} />;
  }

  return (
    <div className="space-y-8">
      {sections.map((group) => (
        <section key={group.tag?.id ?? "untagged"} className="space-y-3">
          <h3 className="flex items-center gap-2 font-medium text-sm">
            {group.tag ? (
              <TagBadge tag={group.tag} size="sm" />
            ) : (
              <span className="text-muted-foreground">{t("groups.untagged")}</span>
            )}
            <span className="text-muted-foreground text-xs">
              {t("groups.count", { count: group.items.length })}
            </span>
          </h3>
          <MasonryWall entries={entriesOf(group.items)} minColumnWidth={minColumnWidth} />
        </section>
      ))}
    </div>
  );
};
