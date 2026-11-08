/**
 * A full-width banner with its heading on it.
 *
 * The community directory's own header and a community's front page are the same
 * shape: a 4:1 strip running the width of the content area, a title and a
 * subtitle over it, and a layout that stops being a strip on a phone. That
 * shape lives here once; the two callers differ only in the banner they hand it
 * — the directory its shipped artwork, a community the one its admin set.
 *
 * The copy's minimums are what give a banner its height, at every width; the
 * picture covers whatever that comes to. The directory's artwork also fades
 * out along its bottom edge because that fade is painted into the file, which
 * is separate from the fade a community can ask for here.
 *
 * A banner that is only a colour is a band, not a hero: it is sized by the
 * copy on it rather than by the viewport, because there is nothing in it to
 * see and a screen-height rectangle of one colour is just a wall.
 *
 * It also rises behind the shell's sticky bar by that bar's own height, so a
 * community's artwork runs under the recents tabs. Only the picture goes up there:
 * the column holding the badges and the copy pads itself back down by the same
 * amount.
 */

import { type CSSProperties, type ReactNode, useLayoutEffect, useRef, useState } from "react";

import type { CommunityBannerRead } from "@/api/generated/initiativeAPI.schemas";
import { readableTextShadow } from "@/lib/contrastColor";
import { cn } from "@/ui/lib/utils";

/**
 * Widens an element from the padded, centred column a page is rendered in to
 * the whole content area beside the sidebar.
 *
 * How wide that area is depends on the shell around the page — which sidebars
 * are open, and which shell the page is being shown in — so it is measured
 * rather than restated as classes here, and measured again when it changes.
 * Until it has been, the classes on the element still take it out to the edges
 * of the column's padding, so nothing jumps.
 */
export const useFullBleed = <T extends HTMLElement>() => {
  const ref = useRef<T>(null);
  const [style, setStyle] = useState<CSSProperties>();
  // How far in from each of the banner's edges the page's own content column
  // starts — exactly what the banner was widened by, back the other way.
  // Anything on the banner that should line up with the page below it (the
  // left-aligned copy, the badges in the corner) indents by these.
  const [inset, setInset] = useState({ left: 0, right: 0 });
  // How tall the shell's sticky bar above the page is. The banner rises behind
  // it by exactly this much, so the artwork runs under the recents tabs rather
  // than starting beneath them. Zero where there is no such bar — on a phone,
  // where that row is hidden, and in a shell that has none.
  const [header, setHeader] = useState(0);
  // Whether the banner is running in a phone-width content area. It decides
  // how much height the fade may spend, which is the one measurement a media
  // query cannot make here: the banner's width is the content area's, not the
  // viewport's, and the two differ by whichever sidebars are open.
  const [compact, setCompact] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    const column = element?.parentElement;
    const main = element?.closest("main");
    const area = main?.parentElement;
    if (!column || !area) return;
    // The sticky bar is the content area's own previous sibling in the shell.
    const bar = area.previousElementSibling;

    const measure = () => {
      const columnBox = column.getBoundingClientRect();
      const areaBox = area.getBoundingClientRect();
      // Set from the column rather than from the element, whose own box is
      // what these values move.
      setStyle((current) =>
        current?.width === areaBox.width && current?.marginLeft === areaBox.left - columnBox.left
          ? current
          : {
              marginLeft: areaBox.left - columnBox.left,
              marginRight: 0,
              width: areaBox.width,
              maxWidth: "none",
            }
      );
      const left = columnBox.left - areaBox.left;
      const right = areaBox.right - columnBox.right;
      setInset((current) =>
        current.left === left && current.right === right ? current : { left, right }
      );
      const barHeight = bar ? bar.getBoundingClientRect().height : 0;
      setHeader((current) => (current === barHeight ? current : barHeight));
      const narrow = areaBox.width < COMPACT_WIDTH;
      setCompact((current) => (current === narrow ? current : narrow));
    };
    measure();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    observer.observe(column);
    if (bar) observer.observe(bar);
    return () => observer.disconnect();
  }, []);

  return { ref, style, inset, header, compact };
};

/**
 * A fade is a second grid row of `extend` pixels below the banner's own, and
 * exactly that much taken back off the banner's bottom margin.
 *
 * Adding and subtracting the same number is the whole trick: the copy does not
 * move, the page's next element does not move, and the space between them is
 * banner rather than nothing — so the tool rail and the table end up sitting
 * over a banner that is dissolving underneath them. The extra row is a fixed
 * track, and the ground spans both, so the fade band is as much banner as the
 * rest of it — an empty band under a picture that stopped short would be a
 * hard edge over nothing, which is what a fade must not be.
 *
 * The fade begins `extend` plus the same small overlap up from the very
 * bottom: the dissolve covers the whole extra row and reaches a couple of
 * dozen pixels into the banner proper, never further. That is what lets one
 * number serve both a tall photograph and the short band a community with no
 * artwork gets — a percentage stop strong enough to matter on the first would
 * wash out the title on the second.
 *
 * Each strength is two numbers rather than one because a phone has a fraction
 * of the height to spend: 224px of dissolve is a quarter of a laptop's banner
 * and half a phone's screen. The narrow figure is picked from the measured
 * width, in a layout effect, so it is in place before the first paint.
 */
const FADE_OVERLAP = 24;
/** Below this many CSS pixels of content area, a banner is on a phone. */
const COMPACT_WIDTH = 640;
const FADES: Record<
  Exclude<CommunityBannerRead["fade"], "none">,
  { narrow: number; wide: number }
> = {
  weak: { narrow: 28, wide: 48 },
  strong: { narrow: 96, wide: 224 },
};

export type PageBannerProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  /**
   * The banner to render, whole: the picture to run behind the copy, the fill
   * that shows where there is none, the colour the copy is written in, where
   * it sits across the width, and how far the banner dissolves into the page
   * below it. Anything but a `none` fade extends the banner past where it
   * would have ended and fades it out there, so the page's own content rides
   * over the tail.
   *
   * Built by `renderableBanner`, which resolves the picture's URL and answers
   * for a header that has no community banner of its own.
   */
  banner: CommunityBannerRead;
  /** Chips for the banner's top-right corner — a community's roster and room counts. */
  badges?: ReactNode;
  /**
   * A row of its own under the title — a guild's location. Rendered as given:
   * the caller dresses it in the banner's ink.
   */
  meta?: ReactNode;
  /** Alt text for the picture; empty for artwork that says nothing. */
  imageAlt?: string;
  /**
   * Hold the copy at a dark neutral inside a halo of the artwork's own light,
   * instead of using the banner's `text_color`. For a fixed light-toned
   * illustration the theme changes under the words and the picture does not,
   * so the halo is what keeps the detail behind them visible.
   */
  haloOverImage?: boolean;
};

export function PageBanner({
  title,
  subtitle,
  banner: { image_url: imageUrl, color, text_color: ink, text_align: align, fade },
  badges,
  meta,
  imageAlt = "",
  haloOverImage = false,
}: PageBannerProps) {
  const box = useFullBleed<HTMLDivElement>();
  const halo = !!imageUrl && haloOverImage;
  const extend = fade === "none" ? 0 : FADES[fade][box.compact ? "narrow" : "wide"];
  // Masking the ground rather than the whole banner is what keeps the fade off
  // the words: the copy is a sibling of this layer, not a child of it.
  const dissolve: CSSProperties = extend
    ? (() => {
        const gradient = `linear-gradient(to bottom, #000 calc(100% - ${extend + FADE_OVERLAP}px), transparent 100%)`;
        return { maskImage: gradient, WebkitMaskImage: gradient };
      })()
    : {};

  // It runs the full width of the content area rather than of the page: the
  // shell renders a page in a padded, centred column, and this is widened back
  // out to everything beside the sidebar.
  //
  // With a picture, from `lg` up the image is in flow, sharing a grid cell
  // with the copy, so the banner is as tall as whichever needs more room.
  //
  // The banner's height comes from the copy's minimums at every width, and the
  // picture covers whatever that turns out to be. It has to be that way round
  // rather than the picture setting the height: a fade adds a band of banner
  // below the copy, and a picture sized to its own 4:1 would end above that
  // band and leave it empty — a hard edge over nothing, which is not a fade.
  // Covering also means a title that wraps to more lines opens the banner up
  // and takes the picture with it, and that a phone gets something close to
  // square rather than a strip too short to read a heading on.
  //
  // With only a colour there is no picture to lose by keeping it short — so it
  // is a band the copy sizes, at a smaller type scale, rather than a hero.
  return (
    <div
      ref={box.ref}
      style={{
        ...box.style,
        // Up behind the shell's sticky bar, so the artwork runs under the
        // recents tabs; the copy pads itself back down by the same amount, so
        // only the picture goes up there and none of the words do.
        ...(box.header ? { marginTop: -box.header } : null),
        // The extra row is a fixed track the ground spans; the margin gives
        // back exactly what it added, so nothing below the banner moves.
        ...(extend ? { gridTemplateRows: `auto ${extend}px`, marginBottom: -extend } : null),
      }}
      className="relative -mx-4 -mt-4 grid overflow-hidden md:-mx-8 md:-mt-8"
    >
      {/* The ground: the fill, the artwork, and the fade over both. `gridRow`
          is set outright rather than by `row-start`/`row-span` classes, whose
          longhand and shorthand would be settling which wins between them in
          the stylesheet rather than here. */}
      <div
        style={{
          gridRow: extend ? "1 / span 2" : "1",
          gridColumn: "1",
          ...(imageUrl || !color ? null : { backgroundColor: color }),
          ...dissolve,
        }}
        className="relative"
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={imageAlt}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : null}
      </div>
      {/* The corner and the copy share one column: the badges take a row of
          their own at the top, and the copy has whatever is left. They are in
          flow rather than laid over the words because an overlay only clears
          them by luck — a long name in the short band a community with no artwork
          gets wraps straight under a corner that is floating above it. */}
      <div
        style={{
          gridRow: "1",
          gridColumn: "1",
          // Back down by what the banner rose behind the sticky bar, so the
          // words sit where they always did and only the artwork went up.
          ...(box.header ? { paddingTop: box.header } : null),
        }}
        className={cn(
          "relative flex flex-col",
          // These minimums are the banner's height at every width — the
          // picture covers whatever they come to. They fall away faster than
          // the screen does: a phone has a page to show under the banner and
          // the least room to show it in, so the hero is a band there and only
          // opens out once there is height to spend. `lg` keeps it roughly the
          // proportion the artwork is cut to.
          imageUrl
            ? "min-h-[44vw] sm:min-h-[38vw] md:min-h-[28vw] lg:min-h-[20vw]"
            : "min-h-24 sm:min-h-32 lg:min-h-36"
        )}
      >
        {/* The corner, not the copy: these say how big the community is, which is
            about the banner rather than part of what it says. Held off the
            right edge by the same distance the page's own content is, so they
            line up with what is below them however wide the shell happens to
            be. */}
        {badges ? (
          <div
            style={box.inset.right ? { paddingRight: box.inset.right } : undefined}
            className="flex flex-wrap items-center justify-end gap-2 px-4 pt-4 md:px-8 md:pt-6"
          >
            {badges}
          </div>
        ) : null}
        <div
          // Left-aligned copy lines up with the page's own content rather than
          // with the banner's edge: the banner is pulled out to the full width
          // of the content area, and this puts the words back where the tool
          // rail and the table below them start. Centred copy is centred on
          // the whole banner, which is what being centred means. Until the
          // measure lands the class padding holds it, so nothing starts
          // off-screen.
          style={align === "left" && box.inset.left ? { paddingLeft: box.inset.left } : undefined}
          className={cn(
            // The copy takes the height the corner left it and sits in the
            // middle of that, so a banner with badges reads the same as one
            // without — just with the words starting under them.
            "flex flex-1 flex-col justify-center gap-1 px-4 sm:gap-2 md:px-8",
            align === "left" ? "items-start text-left" : "items-center text-center",
            imageUrl ? "py-6 sm:py-10" : "py-5 sm:py-6"
          )}
        >
          <h1
            className={cn(
              "text-balance font-black tracking-tight",
              imageUrl ? "text-3xl sm:text-5xl lg:text-6xl" : "text-xl sm:text-3xl lg:text-4xl",
              halo &&
                "text-neutral-900 [text-shadow:0_0_10px_rgba(255,255,255,0.95),0_0_28px_rgba(255,255,255,0.8)]"
            )}
            // A shadow of the ink's opposite, so the words survive the patch of
            // artwork the community's one text colour did not anticipate.
            style={halo ? undefined : { color: ink, textShadow: readableTextShadow(ink) }}
          >
            {title}
          </h1>
          {meta ? (
            <div
              className={cn(
                "flex max-w-full",
                align === "left" ? "justify-start" : "justify-center",
                halo && "text-neutral-800"
              )}
            >
              {meta}
            </div>
          ) : null}
          {subtitle ? (
            <p
              className={cn(
                "max-w-2xl text-balance font-medium",
                imageUrl ? "text-sm sm:text-lg lg:text-xl" : "text-xs sm:text-base",
                halo &&
                  "text-neutral-800 [text-shadow:0_0_8px_rgba(255,255,255,0.95),0_0_20px_rgba(255,255,255,0.8)]"
              )}
              // Slightly softened against the fill, the way the halo variant is.
              style={
                halo
                  ? undefined
                  : { color: ink, opacity: 0.88, textShadow: readableTextShadow(ink) }
              }
            >
              {subtitle}
            </p>
          ) : null}
        </div>
      </div>
      {/* The fade's own row. Nothing in it — the ground behind it is the whole
          point, and the page's next element is pulled back over it. */}
      {extend ? <div style={{ gridRow: "2", gridColumn: "1" }} /> : null}
    </div>
  );
}
