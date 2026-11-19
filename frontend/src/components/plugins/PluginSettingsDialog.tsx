/**
 * How one plug-in connects, opened from the gear beside it in the sidebar.
 *
 * **Every installed plug-in has this**, whether or not it has a page of its own,
 * so setting one up happens beside the plug-in it is about.
 *
 * - **Everyone** gets the two answers that are theirs: whether the plug-in may act
 *   as them, and their own account at its vendor. Nobody else's appears.
 * - **The seat** also sets the community's own credential here, and the gear in
 *   the title bar opens the plug-in's row in community settings, where its
 *   settings, placement, access and updates are.
 */

import { Link } from "@tanstack/react-router";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PluginConnectionsPanel } from "@/components/plugins/PluginConnectionsPanel";
import { PluginConsentRequests } from "@/components/plugins/PluginConsentRequests";
import { PluginPlanEnded } from "@/components/plugins/PluginOffer";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import { useCommunityPath } from "@/lib/communityUrl";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";

export interface PluginSettingsDialogProps {
  pluginId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PluginSettingsDialog({ pluginId, open, onOpenChange }: PluginSettingsDialogProps) {
  const { t } = useTranslation(["plugins", "common"]);
  const gp = useCommunityPath();
  const { activeCommunity } = useCommunities();
  const detail = useCommunityPluginDetail(pluginId);
  const plugin = detail.data;
  // The community's credential and the install's settings are the seat's.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2 pr-6">
            <DialogTitle>{plugin?.name ?? t("plugins:title")}</DialogTitle>
            {holdsTheSeat && (
              <Button
                size="icon"
                variant="ghost"
                className="ml-auto h-7 w-7"
                asChild
                aria-label={t("plugins:settings.communitySettings")}
                title={t("plugins:settings.communitySettings")}
              >
                <Link
                  to={gp("/settings/integrations")}
                  search={{ plugin: pluginId }}
                  onClick={() => onOpenChange(false)}
                >
                  <Settings2 className="h-4 w-4" aria-hidden />
                </Link>
              </Button>
            )}
          </div>
          <DialogDescription>{t("plugins:settings.description")}</DialogDescription>
        </DialogHeader>
        <PluginConnectBody pluginId={pluginId} />
      </DialogContent>
    </Dialog>
  );
}

/**
 * What a plug-in needs connected, and what it asked to do as the reader: this
 * dialog's body, and the last step of adding a plug-in.
 */
export function PluginConnectBody({ pluginId }: { pluginId: number }) {
  const { activeCommunity } = useCommunities();
  const detail = useCommunityPluginDetail(pluginId);
  const plugin = detail.data;

  if (detail.isLoading || !plugin) {
    return (
      <SkeletonRegion>
        <FormSkeleton card={false} fields={3} action={false} />
      </SkeletonRegion>
    );
  }

  return (
    <div className="space-y-6">
      <PluginPlanEnded plugin={plugin} />
      {/* Yours first. A plug-in that acts as people asks everybody, admins
          included — a community admin's own name is not something their role
          answers for. */}
      {(plugin.consents?.length ?? 0) > 0 && (
        <section className="rounded-lg border p-4">
          <PluginConsentRequests
            pluginId={plugin.id}
            pluginName={plugin.name}
            consents={plugin.consents ?? []}
          />
        </section>
      )}

      <PluginConnectionsPanel
        pluginId={plugin.id}
        connections={plugin.connections}
        canManage={Boolean(activeCommunity?.can.seat)}
      />
    </div>
  );
}
