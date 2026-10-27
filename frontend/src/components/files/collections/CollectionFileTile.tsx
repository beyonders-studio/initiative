import { Check } from "lucide-react";
import { type CSSProperties, memo } from "react";

import { FileKind, type FileSummary } from "@/api/generated/initiativeAPI.schemas";
import { LazyImage } from "@/components/shared/LazyImage";
import type { GridToggleOptions } from "@/hooks/useGridSelection";
import { FILE_TILE_RATIO } from "@/lib/collections";
import { fileIcon } from "@/lib/fileIcon";
import { filePicture } from "@/lib/fileUtils";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface CollectionFileTileProps {
  file: FileSummary;
  /** Open it, or — while selecting — take it into the selection. `extend` is
   *  set when the click held shift, asking for a range. */
  onActivate: (options: GridToggleOptions) => void;
  /** Whether the wall is in selection mode, and whether this one is in it. */
  selecting?: boolean;
  selected?: boolean;
  /** `shape` keeps the wall's shape for the file; `square` crops it to a tile. */
  fit?: "shape" | "square";
  className?: string;
  style?: CSSProperties;
}

/**
 * One file on the wall.
 *
 * A button, not a link: a picture opens in the lightbox over the wall it is
 * on, and any other file on its own page. The name is on hover and never in
 * the layout for a picture — the wall is for looking, and a caption under
 * every tile would make it a list. A file with no picture shows its mark and
 * its name, which is all there is to look at.
 *
 * The same button takes the file into a selection while the wall is
 * selecting, rather than a second control appearing over it: the tile is
 * already the whole target, and a checkbox in the corner of a thumbnail is a
 * smaller one. Shift asks for a range from the last file clicked.
 */
const CollectionFileTileInner = ({
  file,
  onActivate,
  selecting = false,
  selected = false,
  fit = "shape",
  className,
  style,
}: CollectionFileTileProps) => {
  const picture = filePicture(file);
  const ratio = fit === "square" ? 1 : FILE_TILE_RATIO;
  const { Icon, colorClass } = fileIcon(file);

  return (
    <button
      type="button"
      onClick={(event) => onActivate({ extend: event.shiftKey })}
      aria-label={file.name}
      aria-pressed={selecting ? selected : undefined}
      style={style}
      className={cn(
        "group relative block w-full overflow-hidden rounded-lg bg-muted text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selecting ? "cursor-pointer" : file.kind === FileKind.image ? "cursor-zoom-in" : "",
        selected && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        className
      )}
    >
      {picture ? (
        <LazyImage
          src={resolveUploadUrl(picture)}
          alt={file.name}
          aspectRatio={ratio}
          className={cn("h-full w-full", selecting && !selected && "opacity-90")}
          imgClassName={cn("transition duration-300", !selecting && "group-hover:scale-[1.03]")}
        />
      ) : (
        <span
          className="flex h-full w-full flex-col items-center justify-center gap-2 p-3"
          style={{ aspectRatio: ratio }}
        >
          <Icon className={cn("size-10", colorClass)} aria-hidden />
          <span className="line-clamp-2 text-center text-muted-foreground text-xs">
            {file.name}
          </span>
        </span>
      )}
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
      {picture && !selecting && (
        <span className="pointer-events-none absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-2 pt-6 pb-1.5 text-white text-xs opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
          {file.name}
        </span>
      )}
    </button>
  );
};

export const CollectionFileTile = memo(CollectionFileTileInner);
