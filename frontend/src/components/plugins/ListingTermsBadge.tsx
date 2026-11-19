/**
 * What a listing costs, when the package this deployment reads says: paid, or
 * included with Initiative. Everything else, the public registry's listings
 * among them, is free and carries no mark.
 *
 * A paid one says how it is sold when billing's offer to this community does:
 * a subscription or a one-time purchase. Without an offer (the community
 * already holds it, or nothing sells here) it says only that it is paid.
 */

import { Gem, Repeat, Tag } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ListingUnavailable } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";
import { cn } from "@/ui/lib/utils";

export function ListingTermsBadge({
  listing,
  className,
}: {
  listing: { paid: boolean; included: boolean; unavailable?: ListingUnavailable | null };
  className?: string;
}) {
  const { t } = useTranslation("marketplace");
  if (listing.included) {
    return (
      <Badge
        variant="outline"
        className={cn(
          "gap-1 border-transparent bg-violet-500/15 text-violet-700 dark:text-violet-300",
          className
        )}
      >
        <Gem className="size-3.5" aria-hidden />
        {t("card.included")}
      </Badge>
    );
  }
  if (listing.paid) {
    const charge = listing.unavailable?.offer?.charge;
    const Icon = charge === "subscription" ? Repeat : Tag;
    return (
      <span
        className={cn("inline-flex items-center gap-1 text-muted-foreground text-xs", className)}
      >
        <Icon className="size-3.5" aria-hidden />
        {charge === "subscription"
          ? t("card.subscription")
          : charge === "one_time"
            ? t("card.oneTime")
            : t("card.paid")}
      </span>
    );
  }
  return null;
}
