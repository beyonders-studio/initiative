/**
 * "Where should this go?"
 *
 * A tool's listing belongs to an initiative, so installing one is a choice of
 * which. The picker offers only the initiatives where the viewer may create
 * that tool — the same permission the create flow uses, and the same one the
 * server checks — so the list is what the install will actually accept.
 *
 * The definition is never sent. The request names the listing; the server reads
 * what that listing publishes.
 *
 * A dashboard is created from its listing by the dashboards endpoint, which
 * takes a name of its own. Every other tool installs through the marketplace's
 * install, which imports a copy: of the listing as published or of its
 * example, with its dates moved to start on the day the installer picks.
 */

import { useNavigate } from "@tanstack/react-router";
import { format } from "date-fns";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ListingStartFrom,
  type MarketplaceListingDetail,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { useInstallMarketplaceListing } from "@/api/generated/marketplace/marketplace";
import { invalidate, q } from "@/api/query-keys";
import { ListingProvenance } from "@/components/marketplace/ListingProvenance";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateDashboard } from "@/hooks/useDashboards";
import { useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { listingShownHere } from "@/lib/marketplaceCuration";
import { toast } from "@/lib/mascotToast";
import { projectEnvelopeHasDates, readProjectEnvelope } from "@/lib/projectListing";
import { toolDetailRoute } from "@/lib/tools";
import type { DialogProps } from "@/types/dialog";
import { DateTimePicker } from "@/ui/date-time-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

export interface InstallListingDialogProps extends DialogProps {
  listing: MarketplaceListingDetail;
  /** The tool the listing installs into, read from its kind. */
  tool: Tool;
  /** Pre-selected when the viewer arrived from an initiative. */
  defaultInitiativeId?: number;
}

export function InstallListingDialog({
  listing,
  tool,
  defaultInitiativeId,
  open,
  onOpenChange,
}: InstallListingDialogProps) {
  const { t } = useTranslation(["marketplace", "common"]);
  const navigate = useNavigate();
  const gp = useCommunityPath();
  const communityId = useActiveCommunityId();

  const isDashboard = tool === Tool.dashboard;
  const { creatableInitiatives } = useToolCreateAccess(tool);
  const [initiativeId, setInitiativeId] = useState<string>("");
  const [name, setName] = useState(listing.name);
  const [startFrom, setStartFrom] = useState<ListingStartFrom>(ListingStartFrom.blank);
  const [startsOn, setStartsOn] = useState(() => format(new Date(), "yyyy-MM-dd"));
  const createDashboard = useCreateDashboard();
  const installCopy = useInstallMarketplaceListing();
  const isPending = createDashboard.isPending || installCopy.isPending;

  // A dashboard's example is generated sample data, there to preview and never
  // to install.
  const offersExample = !isDashboard && Boolean(listing.example);
  const installing = startFrom === ListingStartFrom.example ? listing.example : listing.definition;
  const asksForStart =
    tool === Tool.project && projectEnvelopeHasDates(readProjectEnvelope(installing));

  // Seeded once the options are known: the initiative the viewer came from when
  // they may create there, otherwise the only one they can.
  useEffect(() => {
    if (initiativeId || !creatableInitiatives.length) return;
    const fromContext = creatableInitiatives.find((i) => i.id === defaultInitiativeId);
    setInitiativeId(String((fromContext ?? creatableInitiatives[0]).id));
  }, [creatableInitiatives, defaultInitiativeId, initiativeId]);

  const installed = (createdName: string, createdId: number | null | undefined) => {
    toast.success(t("marketplace:install.done", { name: createdName }));
    onOpenChange(false);
    if (createdId != null) {
      navigate({ to: gp(toolDetailRoute(tool, Number(initiativeId), createdId)) });
    }
  };
  const failed = (error: unknown) => {
    toast.error(getErrorMessage(error, "marketplace:install.failed"));
  };

  const submit = () => {
    if (!initiativeId) return;
    if (isDashboard) {
      createDashboard.mutate(
        {
          name: name.trim() || listing.name,
          initiative_id: Number(initiativeId),
          listing_uid: listing.uid,
        },
        { onSuccess: (dashboard) => installed(dashboard.name, dashboard.id), onError: failed }
      );
      return;
    }
    installCopy.mutate(
      {
        communityId,
        uid: listing.uid,
        data: {
          initiative_id: Number(initiativeId),
          start_from: startFrom,
          starts_on: asksForStart && startsOn ? startsOn : undefined,
        },
      },
      {
        onSuccess: ({ result }) => {
          void invalidate(q.toolList(tool));
          installed(result.entity_title || listing.name, result.entity_id);
        },
        onError: failed,
      }
    );
  };

  const nowhereToInstall = creatableInitiatives.length === 0;

  // Only the catalogue this app shows can be installed from it.
  if (!listingShownHere(listing)) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("marketplace:install.title", { name: listing.name })}</DialogTitle>
          <DialogDescription>
            {isDashboard
              ? t("marketplace:install.description")
              : t("marketplace:install.descriptionCopy")}
          </DialogDescription>
        </DialogHeader>

        {/* The last place to see who wrote this, while it is still a choice. */}
        <ListingProvenance listing={listing} />

        {nowhereToInstall ? (
          <p className="text-muted-foreground text-sm">{t("marketplace:install.noInitiatives")}</p>
        ) : (
          <div className="space-y-4">
            <Field label={t("marketplace:install.initiative")} className="space-y-1.5">
              <Select value={initiativeId} onValueChange={setInitiativeId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {creatableInitiatives.map((initiative) => (
                    <SelectItem key={initiative.id} value={String(initiative.id)}>
                      {initiative.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            {isDashboard ? (
              <Field label={t("marketplace:install.name")} className="space-y-1.5">
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={listing.name}
                />
              </Field>
            ) : null}

            {offersExample ? (
              <RadioGroup
                value={startFrom}
                onValueChange={(value) => setStartFrom(value as ListingStartFrom)}
                aria-label={t("marketplace:install.startFrom")}
                className="gap-2"
              >
                <div className="flex items-center gap-2">
                  <RadioGroupItem value={ListingStartFrom.blank} id="install-start-blank" />
                  <Label htmlFor="install-start-blank">{t("marketplace:install.startBlank")}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <RadioGroupItem value={ListingStartFrom.example} id="install-start-example" />
                  <Label htmlFor="install-start-example">
                    {t("marketplace:install.startExample")}
                  </Label>
                </div>
              </RadioGroup>
            ) : null}

            {asksForStart ? (
              <Field
                label={t("marketplace:install.startsOn")}
                hint={t("marketplace:install.startsOnHelp")}
                className="space-y-1.5"
              >
                <DateTimePicker value={startsOn} onChange={setStartsOn} includeTime={false} />
              </Field>
            ) : null}
          </div>
        )}

        <DialogFooter
          submitLabel={
            <>
              <Download className="h-4 w-4" />
              {t("marketplace:install.action")}
            </>
          }
          onSubmit={submit}
          pending={isPending}
          disabled={nowhereToInstall || !initiativeId}
        />
      </DialogContent>
    </Dialog>
  );
}
