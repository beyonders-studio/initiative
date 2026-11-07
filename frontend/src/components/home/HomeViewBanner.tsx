/**
 * A home view's banner: the artwork across the top of the page, with the
 * view's tabs and controls riding on it and the widgets rising over its lower
 * part as it fades out.
 *
 * A band rather than a hero. A profile's or a community's banner carries a
 * heading; a home view's is the backdrop to a page that is about its widgets.
 * It runs the full width of the content area and up behind the shell's sticky
 * bar, as the other banners do (`useFullBleed`), and what rides on it lands
 * exactly where it would sit on a view with no banner — switching views never
 * moves the tab bar.
 */

import type { ReactNode } from "react";

import { useFullBleed } from "@/components/PageBanner";
import { cn } from "@/ui/lib/utils";

/** The artwork fades to nothing over its lower part, where the widgets sit. */
const FADE = "linear-gradient(to bottom, #000 35%, transparent 100%)";

export function HomeViewBanner({
  imageUrl,
  children,
}: {
  /** The artwork, or none: then this is only a frame around what rides on it. */
  imageUrl: string | null;
  /** What rides at the top of the banner: the tabs and the page's controls. */
  children: ReactNode;
}) {
  const box = useFullBleed<HTMLDivElement>();
  // The same elements with or without artwork, so the banner arriving (or
  // being taken off) never remounts what rides on it.
  const on = Boolean(imageUrl);
  return (
    // Out over the page's padding — the width by the measured style, the top
    // by the class — so the artwork meets the edges of the content area. Its
    // own formatting context (`flow-root`), so the rise behind the sticky bar
    // below adds to this pull instead of collapsing into it: two negative
    // margins that touch would leave only the larger, and the controls would
    // land lower than on a view with no banner.
    <div
      ref={box.ref}
      style={on ? box.style : undefined}
      className={cn(on && "relative -mx-4 -mt-4 flow-root md:-mx-8 md:-mt-8")}
    >
      {/* Up behind the sticky bar by its height, in a box of its own so the
          rise adds to the pull over the padding rather than replacing it. A
          band, not a hero: tall enough for the artwork to show above the
          widgets rising over it, short enough that the page is still theirs. */}
      <div
        style={on && box.header ? { marginTop: -box.header } : undefined}
        className={cn(on && "relative min-h-56 sm:min-h-64 md:min-h-72 lg:min-h-80")}
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 h-full w-full object-cover"
            style={{ maskImage: FADE, WebkitMaskImage: FADE }}
          />
        ) : null}
        {/* Back down by the bar's height and the page's padding, and in by
            the inset the banner was widened by: the controls sit exactly
            where the page's own content starts. */}
        <div
          style={
            on
              ? {
                  ...(box.header ? { paddingTop: box.header } : null),
                  ...(box.inset.left ? { paddingLeft: box.inset.left } : null),
                  ...(box.inset.right ? { paddingRight: box.inset.right } : null),
                }
              : undefined
          }
          className={cn(on && "relative px-4 md:px-8")}
        >
          <div className={cn(on && "pt-4 md:pt-8")}>{children}</div>
        </div>
      </div>
    </div>
  );
}
