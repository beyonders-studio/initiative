/**
 * One listing on the browse grid.
 *
 * The artwork is the listing's own — every listing ships custom art, so this
 * never falls back to a product icon and one listing never looks like another.
 * It renders as a plain `<img>`; a listing supplies a URL, never markup.
 */

import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { MarketplaceListingSummary } from "@/api/generated/initiativeAPI.schemas";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { useCommunityPath } from "@/lib/communityUrl";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { Badge } from "@/ui/badge";
import { Card, CardContent } from "@/ui/card";
import { cn } from "@/ui/lib/utils";

export interface MarketplaceCardProps {
  listing: MarketplaceListingSummary;
  /** Set when this community already has an install of this listing. */
  installedCount?: number;
}

export function MarketplaceCard({ listing, installedCount = 0 }: MarketplaceCardProps) {
  const { t } = useTranslation("marketplace");
  const gp = useCommunityPath();

  return (
    <Card className="h-full transition-colors hover:border-primary/50">
      <Link
        to={gp(`/marketplace/${listing.public_id}`)}
        // Carry the shelf through, so going back from a listing returns to the
        // one you were browsing rather than to the dashboards.
        search={{ kind: listing.kind }}
        className="block h-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <CardContent className="flex h-full gap-3 p-4">
          <img
            src={resolveArtworkUrl(listing.avatar_url) ?? undefined}
            alt=""
            aria-hidden
            className="h-12 w-12 shrink-0 rounded-lg object-cover"
            loading="lazy"
          />
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-start justify-between gap-2">
              <h3 className="truncate font-medium text-sm">{listing.name}</h3>
              {installedCount > 0 && (
                <Badge variant="secondary" className="shrink-0">
                  {t("card.installed")}
                </Badge>
              )}
            </div>
            {/* The card answers "who wrote this?" before the click, and the
                author's own address is left off: the whole card is already a
                link, and a link inside a link is neither valid nor clickable. */}
            <ListingProvenance listing={listing} className="truncate" />
            <p className="mt-1.5 line-clamp-2 text-muted-foreground text-sm">
              {listing.description}
            </p>
            <div className={cn("mt-auto flex items-center gap-2 pt-2")}>
              {listing.latest_version && (
                <span className="text-muted-foreground text-xs">
                  {t("card.version", { version: listing.latest_version.version })}
                </span>
              )}
              {!listing.installable ? (
                <Badge variant="outline" className="text-xs">
                  {t("card.needsUpdate")}
                </Badge>
              ) : (
                listing.unavailable && (
                  <Badge variant="outline" className="text-xs">
                    {/* A full term is asked for, not waited on: the listing's
                        page carries the request. */}
                    {listing.unavailable.reason === "term_full"
                      ? t("card.request")
                      : t("card.unavailable")}
                  </Badge>
                )
              )}
            </div>
          </div>
        </CardContent>
      </Link>
    </Card>
  );
}
