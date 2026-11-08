/**
 * One listing's page: what it is, what it looks like, and how to get it.
 *
 * The preview runs the real pipeline — the listing's definition through the same
 * canvas, sandbox, and renderer a live dashboard uses — over **sample rows**.
 * A listing is not installed, so it has no initiative to read and is given
 * none: the canvas is told to draw samples, which fetches nothing at all.
 *
 * That is the point rather than a convenience. What someone shopping needs to
 * see is the *shape* of the dashboard, and a preview drawn from their own data
 * would be misleading twice over: it would look empty for a new initiative that
 * has nothing yet, and it would read as if the listing already knew about
 * their work.
 *
 * A project listing is drawn the same way, on the real board: its own
 * envelope's statuses and tasks, dated from today, and nothing read from the
 * community either.
 */

import { Link, useParams, useSearch } from "@tanstack/react-router";
import { Download, SearchX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { DashboardCanvas } from "@/components/initiativeTools/dashboards/DashboardCanvas";
import { InstallListingDialog } from "@/components/marketplace/InstallListingDialog";
import { InstallPluginDialog } from "@/components/marketplace/InstallPluginDialog";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { ProjectListingPreview } from "@/components/marketplace/ProjectListingPreview";
import { ReportButton } from "@/components/moderation/ReportButton";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import { useWidgetCatalog } from "@/hooks/useDashboards";
import { useMarketplaceListing } from "@/hooks/useMarketplace";
import { useCommunityPath } from "@/lib/communityUrl";
import { minimumAgeFor, parseCommunityShelf } from "@/lib/marketplace";
import { listingShownHere } from "@/lib/marketplaceCuration";
import { listingKindTool } from "@/lib/tools";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { readConfig, readDefinition } from "@/lib/widgets/definition";
import { Badge } from "@/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/ui/breadcrumb";
import { Button } from "@/ui/button";
import { Skeleton } from "@/ui/skeleton";
import { StatusMessage } from "@/ui/status-message";

export function MarketplaceListingPage() {
  const { t } = useTranslation(["marketplace", "plugins"]);
  const { publicId } = useParams({ strict: false }) as { publicId: string };
  const { kind: shelf } = useSearch({ strict: false }) as { kind?: ListingKind };
  const gp = useCommunityPath();

  const listingQuery = useMarketplaceListing(publicId ?? null);
  const catalogQuery = useWidgetCatalog();
  const [installing, setInstalling] = useState(false);
  const { activeCommunity } = useCommunities();

  const listing = listingQuery.data;
  const isPlugin = listing?.kind === ListingKind.plugin;
  // The tool a listing installs into; none for a plug-in or an automation.
  const tool = listing ? listingKindTool(listing.kind) : null;
  // What the plug-in declares for the viewer's region; nothing enforces it here.
  const minimumAge = isPlugin
    ? minimumAgeFor(listing?.definition, globalThis.navigator?.language)
    : null;
  // Back to the shelf this listing was found on, falling back to the listing's
  // own kind when someone arrived by direct link. Both can be unknown when the
  // listing failed to load, and neither is guaranteed to be a shelf this
  // marketplace has — so the link is built the same way the browse route reads
  // it, and lands on the default shelf rather than on nothing.
  const backToShelf = { kind: parseCommunityShelf(shelf ?? listing?.kind) };
  // Installing a plug-in is a community-admin action; the server enforces it, and the
  // button says so rather than failing after the click.
  // Adding a plug-in is the superadmin's consent, so only the seat is offered it.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  // A listing this community cannot install yet says why, and where the seat
  // can do something about it.
  const unavailable = listing?.unavailable ?? null;
  const { billing, canSell, openAddress, openPortal } = useBillingPortal();
  const actionUrl = unavailable?.action_url ?? null;
  // The deployment's term has no seat free for this community: the way on is
  // a request to its owners, which the seat makes in the billing portal.
  const termFull = unavailable?.reason === "term_full";
  // Whether this community already has it. Every member may read the installs, so
  // this answers for the person asking as well as the one who could act.
  //
  // Three states, not two: undefined while the answer is still loading or the
  // request failed. "We do not know" and "you do not have it" would otherwise
  // render identically — as an install button and a note telling a member to go
  // ask for something they may already have.
  const pluginInstalls = useCommunityPlugins({ enabled: isPlugin });
  const isInstalled: boolean | undefined =
    isPlugin && !pluginInstalls.isLoading && !pluginInstalls.isError
      ? (pluginInstalls.data?.items ?? []).some((plugin) => plugin.listing_uid === listing?.uid)
      : undefined;

  if (listingQuery.isError) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notFound")}
        description={t("detail.notFoundDescription")}
        backTo={gp("/marketplace")}
        backSearch={backToShelf}
        backLabel={t("backToMarketplace")}
      />
    );
  }

  // Reached by a link from outside the shelf this app shows.
  if (listing && !listingShownHere(listing)) {
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("detail.notAvailableHere")}
        description={t("detail.notAvailableHereDescription")}
        backTo={gp("/marketplace")}
        backSearch={backToShelf}
        backLabel={t("backToMarketplace")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp("/marketplace")} search={backToShelf}>
                {t("title")}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            {listing ? (
              <BreadcrumbPage>{listing.name}</BreadcrumbPage>
            ) : (
              <Skeleton className="h-4 w-32" />
            )}
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex flex-wrap items-start gap-4">
        {listing ? (
          <img
            src={resolveArtworkUrl(listing.avatar_url) ?? undefined}
            alt=""
            aria-hidden
            className="h-16 w-16 shrink-0 rounded-xl object-cover"
          />
        ) : (
          <Skeleton className="h-16 w-16 rounded-xl" />
        )}

        <div className="min-w-0 flex-1 space-y-1">
          {listing ? (
            <>
              <div className="flex items-center gap-1">
                <h1 className="font-semibold text-3xl tracking-tight">{listing.name}</h1>
                {!listing.first_party && (
                  <ReportButton targetType="marketplace_listing" targetId={listing.id} />
                )}
              </div>
              <ListingProvenance listing={listing} className="text-sm" />
              <div className="flex flex-wrap items-center gap-2 pt-1">
                {listing.latest_version && (
                  <Badge variant="secondary">
                    {t("card.version", { version: listing.latest_version.version })}
                  </Badge>
                )}
                {minimumAge != null && (
                  <Badge variant="outline">{t("detail.minimumAge", { age: minimumAge })}</Badge>
                )}
                <span className="text-muted-foreground text-xs">
                  {t("detail.installs", { count: listing.installs_count })}
                </span>
              </div>
            </>
          ) : (
            <Skeleton className="h-9 w-56" />
          )}
        </div>

        {listing && (
          <div className="flex flex-col items-end gap-1">
            {isInstalled ? (
              <Badge variant="secondary">{t("card.installed")}</Badge>
            ) : (
              <Button
                onClick={() => setInstalling(true)}
                // Unknown installed state disables it too: offering to add
                // something the community may already have is the one action this
                // page should not take on a guess.
                disabled={
                  !listing.installable ||
                  unavailable !== null ||
                  (isPlugin ? !holdsTheSeat || isInstalled === undefined : !tool)
                }
              >
                <Download className="h-4 w-4" />
                {isPlugin ? t("plugins:install.action") : t("detail.install")}
              </Button>
            )}
            {!listing.installable ? (
              <span className="text-muted-foreground text-xs">
                {listing.available ? t("detail.needsUpdate") : t("detail.withdrawn")}
              </span>
            ) : termFull && !isInstalled ? (
              <div className="flex max-w-xs flex-col items-end gap-1 text-right">
                <span className="text-muted-foreground text-xs">
                  {t("plugins:install.termFull", { name: listing.name })}
                </span>
                {holdsTheSeat && billing && activeCommunity ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void openPortal(activeCommunity.id, "manage", null, {
                        request: "plugin",
                        listing: listing.uid,
                      })
                    }
                  >
                    {t("plugins:install.termFullRequest")}
                  </Button>
                ) : (
                  <span className="text-muted-foreground text-xs">
                    {t("plugins:install.termFullAskAdmins")}
                  </span>
                )}
              </div>
            ) : unavailable && !isInstalled ? (
              <div className="flex max-w-xs flex-col items-end gap-1 text-right">
                <span className="text-muted-foreground text-xs">
                  {t("plugins:install.entitlementRequired")}
                </span>
                {holdsTheSeat && canSell && actionUrl && activeCommunity && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void openAddress(activeCommunity.id, actionUrl)}
                  >
                    {t("plugins:install.entitlementAction")}
                  </Button>
                )}
              </div>
            ) : isPlugin && pluginInstalls.isError ? (
              <span className="text-muted-foreground text-xs">
                {t("plugins:install.unknownState")}
              </span>
            ) : (
              isPlugin &&
              !holdsTheSeat &&
              isInstalled === false && (
                <span className="text-muted-foreground text-xs">
                  {t("plugins:install.adminOnly")}
                </span>
              )
            )}
          </div>
        )}
      </div>

      {listing?.long_description && (
        <p className="max-w-3xl whitespace-pre-line text-sm leading-relaxed">
          {listing.long_description}
        </p>
      )}

      {listing?.images?.length ? (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {listing.images.map((image) => (
            <img
              key={image}
              src={resolveArtworkUrl(image) ?? undefined}
              alt=""
              aria-hidden
              className="h-48 shrink-0 rounded-lg border object-cover"
              loading="lazy"
            />
          ))}
        </div>
      ) : null}

      {/* Each tool previews its own way: a project as its board, a dashboard on
          its canvas. A plug-in mounts one of this build's tools and has nothing
          of its own to draw. */}
      {listing?.kind === ListingKind.project && (
        <div className="space-y-2">
          <h2 className="font-medium text-sm">{t("detail.preview")}</h2>
          <ProjectListingPreview listing={listing} />
        </div>
      )}
      {(!listing || listing.kind === ListingKind.dashboard) && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h2 className="font-medium text-sm">{t("detail.preview")}</h2>
            <p className="text-muted-foreground text-xs">{t("detail.previewIsSample")}</p>
          </div>
          {listing?.definition ? (
            // The same canvas a live dashboard renders, read-only: `canEdit` false
            // means static tiles, no drag handles, and no layout writes.
            <DashboardCanvas
              // A listing is the dashboard's export envelope; the canvas is
              // its `definition`.
              definition={readDefinition(listing.definition.definition)}
              config={readConfig({})}
              catalog={catalogQuery.data}
              // Sample rows, and therefore no initiative: an uninstalled
              // listing reads nothing from this community.
              sampleData
              initiativeId={undefined}
              canEdit={false}
              onLayoutChange={() => {}}
            />
          ) : (
            <Skeleton className="h-64 w-full rounded-lg" />
          )}
        </div>
      )}

      {listing && isPlugin ? (
        <InstallPluginDialog listing={listing} open={installing} onOpenChange={setInstalling} />
      ) : listing && tool ? (
        <InstallListingDialog
          listing={listing}
          tool={tool}
          open={installing}
          onOpenChange={setInstalling}
        />
      ) : null}
    </div>
  );
}
