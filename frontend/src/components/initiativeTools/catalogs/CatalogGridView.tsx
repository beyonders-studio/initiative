import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CatalogItemRead } from "@/api/generated/initiativeAPI.schemas";
import { CatalogItemTile } from "@/components/initiativeTools/catalogs/CatalogItemTile";
import { type VirtualRow, VirtualRows } from "@/components/initiativeTools/catalogs/VirtualRows";
import { TagBadge } from "@/components/tags/TagBadge";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { useWidthClass } from "@/hooks/useWidthClass";
import { groupByTag } from "@/lib/catalogs";

interface CatalogGridViewProps {
  images: CatalogItemRead[];
  groupByTags: boolean;
  onActivate: (image: CatalogItemRead, options: GridToggleOptions) => void;
  selecting?: boolean;
  isSelected?: (image: CatalogItemRead) => boolean;
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
 * a catalog of a thousand pictures is a screen of tiles however far down it
 * has been scrolled.
 */
export const CatalogGridView = ({
  images,
  groupByTags,
  onActivate,
  selecting = false,
  isSelected,
}: CatalogGridViewProps) => {
  const { t } = useTranslation("catalogs");
  const { ref, width } = useWidth();
  const minTile = useWidthClass() === "base" ? MIN_TILE_COMPACT : MIN_TILE;
  const columns = Math.max(1, Math.floor((width + GAP) / (minTile + GAP)));
  const tile = width > 0 ? (width - GAP * (columns - 1)) / columns : minTile;

  const rows = useMemo<VirtualRow[]>(() => {
    const tileRows = (items: CatalogItemRead[], prefix: string): VirtualRow[] => {
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
              {slice.map((image) => (
                <CatalogItemTile
                  key={image.id}
                  image={image}
                  fit="square"
                  onActivate={(options) => onActivate(image, options)}
                  selecting={selecting}
                  selected={isSelected?.(image) ?? false}
                />
              ))}
            </div>
          ),
        });
      }
      return out;
    };

    if (!groupByTags) return tileRows(images, "all");
    return groupByTag(images).flatMap((group) => {
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
                <span className="text-muted-foreground">{t("groups.untagged")}</span>
              )}
              <span className="text-muted-foreground text-xs">
                {t("groups.count", { count: group.items.length })}
              </span>
            </h3>
          ),
        },
        ...tileRows(group.items, key),
      ];
    });
  }, [images, groupByTags, columns, tile, onActivate, selecting, isSelected, t]);

  return <div ref={ref}>{width > 0 && <VirtualRows rows={rows} />}</div>;
};
