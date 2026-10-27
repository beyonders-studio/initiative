import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CollectionFileSummary, FileSummary } from "@/api/generated/initiativeAPI.schemas";
import { CollectionFileTile } from "@/components/files/collections/CollectionFileTile";
import type { CollectionCard } from "@/components/files/collections/collectionLists";
import { type VirtualRow, VirtualRows } from "@/components/files/collections/VirtualRows";
import { TagBadge } from "@/components/tags/TagBadge";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { useWidthClass } from "@/hooks/useWidthClass";
import { groupByTag } from "@/lib/collections";

interface CollectionGridViewProps {
  files: CollectionFileSummary[];
  /** What each file shows under its picture, as the layout says. */
  card?: CollectionCard;
  groupByTags: boolean;
  onActivate: (file: FileSummary, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (file: FileSummary) => boolean;
}

/** The narrowest a tile gets before the grid drops a column. Narrower on a
 *  phone, where three across is a grid and two is a pair. */
const MIN_TILE = 160;
const MIN_TILE_COMPACT = 110;
const GAP = 12;
const HEADING_HEIGHT = 36;

/** The width of the element the grid is drawn in, kept current. */
const useWidth = () => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
};

/**
 * The grid: square tiles, as many across as fit.
 *
 * Virtualized by row. A row is `columns` tiles, or a tag's heading when the
 * wall is grouped, and only the rows near the viewport are in the DOM — so
 * a collection of a thousand files is a screen of tiles however far down it
 * has been scrolled.
 */
export const CollectionGridView = ({
  files,
  card,
  groupByTags,
  onActivate,
  selecting = false,
  isSelected,
}: CollectionGridViewProps) => {
  const { t } = useTranslation("files");
  const { ref, width } = useWidth();
  const minTile = useWidthClass() === "base" ? MIN_TILE_COMPACT : MIN_TILE;
  const columns = Math.max(1, Math.floor((width + GAP) / (minTile + GAP)));
  const tile = width > 0 ? (width - GAP * (columns - 1)) / columns : minTile;

  const rows = useMemo<VirtualRow[]>(() => {
    const tileRows = (items: CollectionFileSummary[], prefix: string): VirtualRow[] => {
      const out: VirtualRow[] = [];
      for (let start = 0; start < items.length; start += columns) {
        const slice = items.slice(start, start + columns);
        out.push({
          key: `${prefix}:${slice[0]?.id ?? start}`,
          estimate: tile + GAP,
          render: () => (
            <div
              className="grid"
              style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap: GAP }}
            >
              {slice.map((file) => (
                <div key={file.id} className="min-w-0">
                  <CollectionFileTile
                    file={file}
                    fit="square"
                    onActivate={(options) => onActivate(file, options)}
                    selecting={selecting}
                    selected={isSelected?.(file) ?? false}
                  />
                  {card?.render(file)}
                </div>
              ))}
            </div>
          ),
        });
      }
      return out;
    };

    if (!groupByTags) return tileRows(files, "all");
    return groupByTag(files).flatMap((group) => {
      const key = group.tag ? `tag-${group.tag.id}` : "untagged";
      return [
        {
          key: `${key}:heading`,
          estimate: HEADING_HEIGHT,
          render: () => (
            <h3 className="flex items-center gap-2 pt-3 font-medium text-sm">
              {group.tag ? (
                <TagBadge tag={group.tag} size="sm" />
              ) : (
                <span className="text-muted-foreground">{t("collections.groups.untagged")}</span>
              )}
              <span className="text-muted-foreground text-xs">
                {t("collections.groups.count", { count: group.items.length })}
              </span>
            </h3>
          ),
        },
        ...tileRows(group.items, key),
      ];
    });
  }, [files, card, groupByTags, columns, tile, onActivate, selecting, isSelected, t]);

  return <div ref={ref}>{width > 0 && <VirtualRows rows={rows} />}</div>;
};
