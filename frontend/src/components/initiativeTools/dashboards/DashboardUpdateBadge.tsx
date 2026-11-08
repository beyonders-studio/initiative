/**
 * "There's a newer version of this."
 *
 * Shown only for a dashboard that was installed from a listing, and only when
 * the version it is pinned to is not the one the listing currently publishes.
 * Taking it is always a click: applying a new version replaces this dashboard's
 * canvas, so it is the author's call and nobody else's — and it re-pins this
 * dashboard alone, leaving any other install of the same listing where it is.
 *
 * A dashboard authored here has no listing and renders nothing at all.
 */

import { ArrowUpCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";
import { useUpgradeDashboard } from "@/hooks/useDashboards";
import { useMarketplaceListingByUid } from "@/hooks/useMarketplace";
import { listingShownHere } from "@/lib/marketplaceCuration";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";

export interface DashboardUpdateBadgeProps {
  dashboard: DashboardRead;
  /** Applying a version rewrites the canvas, so it takes the same write access
   *  that editing does. Without it the badge is informational. */
  canEdit: boolean;
}

export function DashboardUpdateBadge({ dashboard, canEdit }: DashboardUpdateBadgeProps) {
  const { t } = useTranslation("marketplace");
  const listingQuery = useMarketplaceListingByUid(dashboard.listing_uid);
  const upgrade = useUpgradeDashboard(dashboard.id);

  const listing = listingQuery.data;
  const latest = listing?.latest_version;
  // `installable` is the server's own verdict — still offered, has a version,
  // and that version runs on this build — so the button appears only when the
  // upgrade would actually be accepted. Re-deriving it here is how a withdrawn
  // listing ends up offering an update that 409s.
  // A new version is an install, so it is offered only from the catalogue
  // this app shows.
  if (
    !listing?.installable ||
    !latest ||
    latest.version === dashboard.listing_version ||
    !listingShownHere(listing)
  ) {
    return null;
  }

  const apply = () =>
    upgrade.mutate(undefined, {
      onSuccess: (updated) => {
        toast.success(t("update.done", { version: updated.listing_version }));
      },
    });

  if (!canEdit) {
    return (
      <span className="text-muted-foreground text-xs">
        {t("update.available", { version: latest.version })}
      </span>
    );
  }

  return (
    <Button size="sm" variant="outline" onClick={apply} disabled={upgrade.isPending}>
      {upgrade.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <ArrowUpCircle className="h-4 w-4" />
      )}
      {t("update.available", { version: latest.version })}
    </Button>
  );
}
