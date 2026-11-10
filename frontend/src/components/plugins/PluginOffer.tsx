/**
 * How this community gets a paid plug-in, as the deployment's billing answers
 * it, and the seat's way to the billing portal to do it.
 *
 * Nothing here decides anything. The deployment's catalog terms say whether
 * the plan this community is on sells the plug-in (`way`), whether a plan
 * above it would (`upgrade`), and what it is sold as (`lines`, already worded
 * and priced by billing in the reader's language); this shows that answer and
 * never words a plan, a price or a reason of its own.
 *
 * With no answer — no billing here, billing unreachable, or a listing billing
 * doesn't sell as an app of its own — it shows `fallback` and, for the seat,
 * the portal address the server gave, as before there were offers.
 *
 * The portal opens in a new tab; the reads behind these pages are asked again
 * when this tab comes back (`useMarketplace`, `useCommunityPluginDetail`), so
 * the install appears once billing's statement has arrived.
 */

import { useTranslation } from "react-i18next";

import type { CommunityPluginDetail, ListingOffer } from "@/api/generated/initiativeAPI.schemas";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useMarketplaceListingByUid } from "@/hooks/useMarketplace";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

export interface PluginOfferProps {
  offer: ListingOffer | null | undefined;
  /** The billing portal page where the seat acts on it. */
  actionUrl: string | null | undefined;
  /** What is said when billing has no answer. */
  fallback?: string;
  /** Still asking: no button yet, rather than one that changes under the pointer. */
  loading?: boolean;
  align?: "start" | "end";
  className?: string;
}

export function PluginOffer({
  offer,
  actionUrl,
  fallback,
  loading = false,
  align = "start",
  className,
}: PluginOfferProps) {
  const { t } = useTranslation("plugins");
  const { activeCommunity } = useCommunities();
  const { canSell, openAddress } = useBillingPortal();
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  const mayAct = holdsTheSeat && canSell && Boolean(actionUrl) && Boolean(activeCommunity);

  const notOffered = offer?.way === "none" && !offer.upgrade;
  const message = !offer
    ? fallback
    : offer.way === "buy"
      ? undefined
      : offer.upgrade
        ? t("offer.notOnPlan")
        : t("offer.notOffered");
  const label = !offer
    ? t("install.entitlementAction")
    : offer.way === "buy"
      ? offer.charge === "one_time"
        ? t("offer.buy")
        : t("offer.choosePlan")
      : offer.upgrade
        ? t("offer.seePlans")
        : null;
  const lines = offer && !notOffered ? offer.lines : [];

  return (
    <div
      className={cn(
        "flex max-w-xs flex-col gap-1 text-xs",
        align === "end" ? "items-end text-right" : "items-start",
        className
      )}
    >
      {message && <span className="text-muted-foreground">{message}</span>}
      {lines.length > 0 && (
        <ul className="space-y-0.5">
          {lines.map((line) => (
            <li key={line.id}>
              <span>{line.name}</span>
              {line.display && <span className="text-muted-foreground"> · {line.display}</span>}
            </li>
          ))}
        </ul>
      )}
      {loading || !label ? null : mayAct && activeCommunity && actionUrl ? (
        <Button
          size="sm"
          variant="outline"
          onClick={() => void openAddress(activeCommunity.id, actionUrl)}
        >
          {label}
        </Button>
      ) : (
        offer &&
        !holdsTheSeat && <span className="text-muted-foreground">{t("install.adminOnly")}</span>
      )}
    </div>
  );
}

/** An installed plug-in whose entitlement statement is inactive for a reason
 *  other than a full term: its plan has ended. The page still opens — what
 *  still works is the plug-in's to decide. */
export const planEnded = (plugin: CommunityPluginDetail | undefined) =>
  plugin?.entitlement?.active === false && plugin.entitlement.reason !== "term_full";

/**
 * "This plug-in's plan has ended", for an installed plug-in that `planEnded`,
 * and for the seat how to get it again: billing's offer, read from the
 * listing's page, or the portal address the install carries.
 */
export function PluginPlanEnded({
  plugin,
  className,
}: {
  plugin: CommunityPluginDetail;
  className?: string;
}) {
  const { t } = useTranslation("plugins");
  const { activeCommunity } = useCommunities();
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  const ended = planEnded(plugin);
  // Only the seat acts on it, so only the seat's page asks billing.
  const listing = useMarketplaceListingByUid(plugin.listing_uid, {
    enabled: ended && holdsTheSeat,
  });
  if (!ended) return null;
  const unavailable = listing.data?.unavailable;

  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-start justify-between gap-2 rounded-lg border bg-muted/40 p-3",
        className
      )}
    >
      <p className="font-medium text-sm">{t("offer.planEnded")}</p>
      {holdsTheSeat && (
        <PluginOffer
          offer={unavailable?.offer}
          actionUrl={unavailable?.action_url ?? plugin.entitlement?.action_url}
          loading={listing.isLoading}
          align="end"
        />
      )}
    </div>
  );
}
