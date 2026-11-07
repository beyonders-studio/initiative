/**
 * Where a community is, on a row of its own: its own name for the place, then
 * the place as its admin typed it ("Queen Anne Neighborhood, Seattle,
 * Washington, United States"). The row is cut to one line wherever it sits,
 * and opens the place on a map unless it sits inside something that is itself
 * clickable.
 */

import { MapPin } from "lucide-react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import { type CommunityLocation, locationMapUrl } from "@/lib/communityLocation";
import { cn } from "@/ui/lib/utils";

export type CommunityLocationLineProps = {
  location: CommunityLocation;
  className?: string;
  /** For a row painted on a banner, in the banner's own ink. */
  style?: CSSProperties;
  /**
   * Whether the row opens the place on a map. Off where the row sits inside
   * something that is itself clickable — a card that is one button — which a
   * link inside would fight.
   */
  interactive?: boolean;
};

export const CommunityLocationLine = ({
  location,
  className,
  style,
  interactive = true,
}: CommunityLocationLineProps) => {
  const { t } = useTranslation("communities");
  const ownName = location.label?.trim();
  const line = ownName ? `${ownName}, ${location.text}` : location.text;
  const label = t("location.ariaLabel", { location: line });
  const rowClass = cn("flex min-w-0 max-w-full items-center gap-1 text-xs", className);
  // When the row runs out of room the community's own name for the place gives
  // way first, so the place itself survives a long neighbourhood name.
  const content = (
    <>
      <MapPin className="size-[1em] shrink-0" aria-hidden="true" />
      {ownName ? <span className="min-w-0 shrink truncate">{ownName},</span> : null}
      <span className="min-w-0 shrink-[0.001] truncate">{location.text}</span>
    </>
  );

  if (!interactive) {
    return (
      <p className={rowClass} style={style} title={line}>
        <span className="sr-only">{label}</span>
        <span aria-hidden="true" className="contents">
          {content}
        </span>
      </p>
    );
  }

  return (
    <a
      href={locationMapUrl(location)}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        rowClass,
        "w-fit rounded-sm underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-current"
      )}
      style={style}
      title={line}
      aria-label={label}
    >
      {content}
    </a>
  );
};
