import { TintedFrame } from "@/components/user/TintedFrame";
import { type Decoration, decorationSrc, FRAME_APERTURE_INSET } from "@/lib/profileDecorations";
import { cn } from "@/ui/lib/utils";

/**
 * One decoration, drawn the way its slot is worn.
 *
 * The three slots want three different shapes — a banner is a strip, a frame is
 * a ring around a face, a trophy is a mark beside a name — and every surface
 * that lists decorations wants the same three. So they are settled once here,
 * and the picker, the store and the pack list only choose how wide to make it.
 *
 * A frame is artwork with a hole in it, which on its own reads as a ring around
 * nothing; the muted disc stands in for the picture so the shape reads.
 */
export const DecorationSwatch = ({
  decoration,
  tint,
  year,
  className,
}: {
  decoration: Decoration;
  /** For a frame whose colours are the wearer's: the ones they have picked. */
  tint?: readonly string[] | null;
  /** For a decoration that carries a year: the one they have picked. */
  year?: number | null;
  className?: string;
}) => {
  const src = decorationSrc(decoration, year);

  if (decoration.kind === "banner") {
    return (
      <span
        className={cn("block h-10 w-full rounded-sm bg-center bg-cover", className)}
        style={{ backgroundImage: `url(${src})` }}
      />
    );
  }

  if (decoration.kind === "frame") {
    return (
      <span className={cn("relative block size-10", className)}>
        <span
          className="absolute rounded-full bg-muted-foreground/20"
          style={{ inset: FRAME_APERTURE_INSET }}
        />
        {decoration.tint ? (
          <TintedFrame decoration={decoration} tint={tint} className="absolute inset-0 size-full" />
        ) : (
          <img src={src} alt="" aria-hidden="true" className="absolute inset-0 size-full" />
        )}
      </span>
    );
  }

  return <img src={src} alt="" aria-hidden="true" className={cn("size-10", className)} />;
};
