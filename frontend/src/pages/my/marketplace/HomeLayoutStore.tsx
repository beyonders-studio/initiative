/**
 * The marketplace's home layouts, on the person's own marketplace: each drawn
 * as a map of where its widgets sit, and added to their home as a new view —
 * the views they already have are left as they are.
 */

import { LayoutTemplate } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { HomeLayoutListing } from "@/api/generated/initiativeAPI.schemas";
import { LayoutMap } from "@/components/home/HomeLayoutsDialog";
import { useHomeLayoutListings } from "@/hooks/useHomeLayoutListings";
import { useHomeViews } from "@/hooks/useHomeViews";
import { layoutFromListing } from "@/lib/home/listing";
import { canAddView, MAX_HOME_VIEWS } from "@/lib/home/views";
import { toast } from "@/lib/mascotToast";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { Button } from "@/ui/button";
import { Card, CardContent } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

const LayoutCard = ({
  listing,
  onAdd,
  disabled,
}: {
  listing: HomeLayoutListing;
  onAdd: () => void;
  disabled: boolean;
}) => {
  const { t } = useTranslation("home");
  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <LayoutMap layout={layoutFromListing(listing)} />
        <div className="flex gap-3">
          {listing.avatar_url ? (
            <img
              src={resolveArtworkUrl(listing.avatar_url) ?? undefined}
              alt=""
              aria-hidden
              className="size-10 shrink-0 rounded-lg object-cover"
              loading="lazy"
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-medium text-sm">{listing.name}</h3>
            <p className="truncate text-muted-foreground text-xs">
              {t("marketplace.by", { publisher: listing.publisher })}
            </p>
          </div>
        </div>
        <p className="text-muted-foreground text-sm">
          {listing.long_description || listing.description}
        </p>
        <div className="mt-auto pt-1">
          <Button type="button" className="w-full" onClick={onAdd} disabled={disabled}>
            {t("store.add")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export function HomeLayoutStore() {
  const { t } = useTranslation("home");
  const listings = useHomeLayoutListings();
  const home = useHomeViews();
  const roomForMore = canAddView(home.views);

  const add = (listing: HomeLayoutListing) => {
    home.create(listing.name, layoutFromListing(listing));
    toast.success(t("store.added", { name: listing.name }));
  };

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="flex items-center gap-2 font-semibold text-xl">
          <LayoutTemplate className="size-5 text-muted-foreground" aria-hidden="true" />
          {t("store.title")}
        </h2>
        <p className="text-muted-foreground text-sm">
          {roomForMore ? t("store.description") : t("views.limit", { max: MAX_HOME_VIEWS })}
        </p>
      </div>
      {listings.isLoading || !home.isLoaded ? (
        <div className="grid grid-cols-fill-64/3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
            <Skeleton key={i} className="h-80 rounded-xl" />
          ))}
        </div>
      ) : listings.isError ? (
        <StatusMessage onRetry={listings.refetch} />
      ) : (listings.data ?? []).length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("marketplace.empty")}</p>
      ) : (
        <ul className="grid grid-cols-fill-64/3 gap-4">
          {(listings.data ?? []).map((listing) => (
            <li key={listing.uid}>
              <LayoutCard listing={listing} onAdd={() => add(listing)} disabled={!roomForMore} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
