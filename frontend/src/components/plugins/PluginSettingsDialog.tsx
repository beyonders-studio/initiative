/**
 * One plug-in's settings, opened from wherever the plug-in is.
 *
 * **Every installed plug-in has this**, whether or not it has a page of its own —
 * there is always something a person may want to check or take back. For a plug-in
 * whose whole purpose is a credential it opens where the member clicked rather
 * than sending them to hunt through community settings; for a plug-in with a page it
 * is the gear beside its entry.
 *
 * What shows is scoped to what the viewer actually controls, which is not the
 * same as what they can see:
 *
 * - **Everyone** gets the two answers that are theirs — whether the plug-in may act
 *   as them, and their own half of any connection. Nobody else's appears.
 * - **The seat** additionally gets what the community owns: the community-wide
 *   credential, the plug-in's settings, where it appears, and the governance
 *   view of what every member has given it.
 *
 * This is deliberately not the community-settings page. That one is about the
 * install — adding, renaming, turning off, removing — and belongs to admins.
 * This one is about a person's own relationship with a plug-in that is already
 * there.
 */

import { useTranslation } from "react-i18next";

import { PluginConnectionsPanel } from "@/components/plugins/PluginConnectionsPanel";
import { PluginConsentRequests } from "@/components/plugins/PluginConsentRequests";
import { PluginMembersPanel } from "@/components/plugins/PluginMembersPanel";
import { PluginPlanEnded } from "@/components/plugins/PluginOffer";
import { PluginPlacementPanel } from "@/components/plugins/PluginPlacementPanel";
import { PluginSettingsPanel } from "@/components/plugins/PluginSettingsPanel";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import { hasInitiativeSurfaces } from "@/lib/pluginSurfaces";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Separator } from "@/ui/separator";

export interface PluginSettingsDialogProps {
  pluginId: number;
  /** Where the plug-in appears is an admin's to choose. */
  isCommunityAdmin: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PluginSettingsDialog({
  pluginId,
  isCommunityAdmin,
  open,
  onOpenChange,
}: PluginSettingsDialogProps) {
  const { t } = useTranslation(["plugins", "common"]);
  const { activeCommunity } = useCommunities();
  const detail = useCommunityPluginDetail(pluginId);
  const plugin = detail.data;

  // Placement is where the plug-in has a page, or fields, sections or actions
  // on items, and where it may reach content, so a plug-in with either has one
  // to choose.
  const showsPlacement =
    isCommunityAdmin &&
    !!plugin &&
    (hasInitiativeSurfaces(plugin.definition) || (plugin.requested_scopes ?? []).length > 0);
  // Install management, which the seat holds — not the manifest's
  // admin-visible surfaces above, which ask whether you administer the
  // community and are a different question.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  const showsAdminSection = holdsTheSeat && !!plugin;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{plugin?.name ?? t("plugins:title")}</DialogTitle>
          <DialogDescription>{t("plugins:settings.description")}</DialogDescription>
        </DialogHeader>
        {detail.isLoading || !plugin ? (
          <SkeletonRegion>
            <FormSkeleton card={false} fields={3} action={false} />
          </SkeletonRegion>
        ) : (
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
              canManage={holdsTheSeat}
            />

            {showsAdminSection && (
              <>
                <Separator />
                <div className="space-y-1">
                  <h2 className="font-medium text-sm">{t("plugins:settings.adminTitle")}</h2>
                  <p className="text-muted-foreground text-xs">
                    {t("plugins:settings.adminDescription")}
                  </p>
                </div>
                <PluginSettingsPanel pluginId={plugin.id} settings={plugin.settings ?? []} />
                {/* Where the plug-in goes is the community's call, and only for a plug-in
                    that has somewhere to go. */}
                {showsPlacement && <PluginPlacementPanel plugin={plugin} />}
                <PluginMembersPanel pluginId={plugin.id} enabled />
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
