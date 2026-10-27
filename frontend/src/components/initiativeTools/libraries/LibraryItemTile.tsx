import { Check, Layers } from "lucide-react";
import { type CSSProperties, memo } from "react";
import { useTranslation } from "react-i18next";

import type { LibraryItemRead } from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { aspectRatio, imageLabel, thumbSrc } from "@/lib/libraries";
import { cn } from "@/lib/utils";

interface LibraryItemTileProps {
  image: LibraryItemRead;
  /** Open it, or — while selecting — take it into the selection. `extend` is
   *  set when the click held shift, asking for a range. */
  onActivate: (options: GridToggleOptions) => void;
  /** Whether the wall is in selection mode, and whether this one is in it. */
  selecting?: boolean;
  selected?: boolean;
  /** `shape` keeps the picture's own shape; `square` crops it to a tile. */
  fit?: "shape" | "square";
  className?: string;
  style?: CSSProperties;
}

/**
 * One picture on the wall.
 *
 * A button, not a link: a picture has no page of its own, it opens in the
 * lightbox over the wall it is on. The title is on hover and never in the
 * layout — the wall is for looking, and a description under every tile would
 * make it a list.
 *
 * The same button takes the picture into a selection while the wall is
 * selecting, rather than a second control appearing over it: the tile is
 * already the whole target, and a checkbox in the corner of a thumbnail is a
 * smaller one. Shift asks for a range from the last picture clicked.
 */
const LibraryItemTileInner = ({
  image,
  onActivate,
  selecting = false,
  selected = false,
  fit = "shape",
  className,
  style,
}: LibraryItemTileProps) => {
  const { t } = useTranslation("libraries");
  const label = imageLabel(image);
  const ratio = fit === "square" ? 1 : (aspectRatio(image) ?? 4 / 3);

  return (
    <button
      type="button"
      onClick={(event) => onActivate({ extend: event.shiftKey })}
      aria-label={label || t("tile.open")}
      aria-pressed={selecting ? selected : undefined}
      style={style}
      className={cn(
        "group relative block w-full overflow-hidden rounded-lg bg-muted text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selecting ? "cursor-pointer" : "cursor-zoom-in",
        selected && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        className
      )}
    >
      <LazyImage
        src={thumbSrc(image)}
        alt={label}
        aspectRatio={ratio}
        className={cn("h-full w-full", selecting && !selected && "opacity-90")}
        imgClassName={cn("transition duration-300", !selecting && "group-hover:scale-[1.03]")}
      />
      {selecting && (
        <span
          aria-hidden
          className={cn(
            "absolute top-2 left-2 flex size-5 items-center justify-center rounded-full border shadow-sm transition-colors",
            selected
              ? "border-primary bg-primary text-primary-foreground"
              : "border-white/70 bg-black/40 text-transparent"
          )}
        >
          <Check className="size-3.5" />
        </span>
      )}
      {image.version_count > 1 && (
        <span
          className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-full bg-black/60 px-1.5 py-0.5 text-3xs text-white"
          title={t("tile.versions", { count: image.version_count })}
        >
          <Layers className="size-3" aria-hidden />
          {image.version_count}
        </span>
      )}
      {label && !selecting && (
        <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-2 pt-6 pb-1.5 text-white text-xs opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
          {label}
        </span>
      )}
    </button>
  );
};

export const LibraryItemTile = memo(LibraryItemTileInner);
