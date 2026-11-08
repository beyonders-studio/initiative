import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { TRAY_SURFACE } from "@/components/toolBrowser/NodeRail";
import { decorationSrc, resolveTrophies } from "@/lib/profileDecorations";
import { cn } from "@/ui/lib/utils";

/**
 * The trophies a profile is wearing, in the order they were put on.
 *
 * The same rail a community puts its tools in: a row of circles standing out
 * of a tray, each with its name printed on the tray under it, and a goo filter
 * welding the two into one silhouette — blur the shapes and push the alpha back
 * to a hard edge (https://css-tricks.com/gooey-effect/). See `NodeRail`,
 * whose circles these are the size of and whose tray this is the same surface
 * as.
 *
 * The goo runs on a layer of its own, holding the tray and a plain disc under
 * each trophy. The artwork and the names sit in a second layer over it,
 * untouched — a filter applies to everything under it, and a name that has been
 * blurred and thresholded is a name nobody can read. Both layers are laid out
 * to the same measurements and scroll together, so the discs stay under the
 * trophies however many are worn.
 *
 * The tray is not decoration. It is what the trophies and their names read
 * against at any brightness, and what makes a collection look like a
 * collection rather than a list. It also holds what the profile has to show —
 * the communities the person is in — the way the community's tray holds the table
 * of whatever its rail has selected. `continues` says the page carries that
 * surface on below the circles, so the tray opens at the bottom instead of
 * closing into a bar of its own.
 *
 * Only the ones this build can draw: an id from a decoration this deployment
 * doesn't have simply isn't in the row, which is what keeps a profile readable
 * after the store stops offering something.
 */
export const ProfileTrophies = ({
  decorations,
  continues = false,
  className,
}: {
  decorations?: ProfileDecorationsOutput | null;
  /** Whether the page continues the tray below the rail. */
  continues?: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  // Two of these can share a page — the profile card and its preview — so the
  // filter is addressed by an id of its own rather than a constant.
  const filterId = `profile-trophies-goo-${useId().replace(/:/g, "")}`;
  const trophies = resolveTrophies(decorations);
  if (trophies.length === 0) return null;

  return (
    <div className={cn("relative", className)}>
      <svg aria-hidden="true" focusable="false" className="pointer-events-none absolute h-0 w-0">
        <defs>
          <filter
            id={filterId}
            colorInterpolationFilters="sRGB"
            // The blur needs more room than a filter region gets by default,
            // or the tops of the circles are cut off by it.
            x="-5%"
            y="-25%"
            width="110%"
            height="150%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur" />
            <feColorMatrix
              in="blur"
              type="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8"
            />
          </filter>
        </defs>
      </svg>
      <div className="relative overflow-x-auto">
        <div className="relative w-max min-w-full">
          {/* The welded silhouette: the tray, and a disc under each trophy. Its
              top edge crosses them at the waist, so half of each one stands
              above it and half is already in it. It closes at the bottom only
              when nothing follows it. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0"
            style={{ filter: `url(#${filterId})` }}
          >
            <div
              className={cn(
                "absolute inset-x-0 top-13 bottom-0",
                continues ? "rounded-t-2xl" : "rounded-2xl",
                TRAY_SURFACE
              )}
            />
            <div className="flex justify-center px-2">
              {trophies.map((trophy) => (
                <div key={trophy.id} className="flex w-24 justify-center pt-5">
                  <div className={cn("size-16 rounded-full", TRAY_SURFACE)} />
                </div>
              ))}
            </div>
          </div>
          <ul
            aria-label={t("trophyRail")}
            className="relative flex items-start justify-center px-2 pb-2"
          >
            {trophies.map((trophy) => (
              <li key={trophy.id} className="flex w-24 flex-col items-center pt-5 text-center">
                <img
                  src={decorationSrc(trophy, decorations?.grad_year)}
                  alt=""
                  className="block size-16"
                />
                <span className="mt-1 w-full text-balance break-words px-1 font-medium text-muted-foreground text-xs leading-tight">
                  {t(trophy.labelKey)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};
