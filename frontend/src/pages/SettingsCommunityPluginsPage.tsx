/**
 * Managing the community's plug-ins.
 *
 * The sidebar shows what is *on*; this is where an admin turns one off, renames
 * it, or removes it — so disabled plug-ins appear here and nowhere else, otherwise
 * turning one off would hide the switch that turns it back on.
 *
 * Removing a plug-in trashes what it created rather than deleting it — and ends
 * every credential it held, the community's and each member's. The confirmation
 * says both: the events a community put in a calendar should not feel like
 * collateral, and nobody should be surprised that access at the vendor stopped.
 *
 * Some plug-ins come with the platform rather than being chosen here. They appear
 * like any other — visible, configurable, renameable — with no switch and no
 * remove button, because whether they exist is the operator's decision rather
 * than the community's. The affordances are absent instead of present-and-refusing.
 *
 * Expanding a row opens what that plug-in actually needs — its connections, grouped
 * — and, for an admin, who has connected to it. Both live behind the expander
 * rather than on the row, because most visits here are to rename or turn
 * something off.
 *
 * That is also where a plug-in's update cadence lives. An install takes new
 * versions on its own unless a community admin turns that off here, after which the
 * Update button beside it is how they land.
 *
 * Whoever runs the server can take plug-ins over for a community. The installed
 * ones keep running and stay listed, members still answer for themselves and the
 * seat can still revoke and block, but nothing here installs, changes or removes
 * one.
 */

import { Link } from "@tanstack/react-router";
import { Blocks, ChevronDown, Loader2, ShieldCheck, Store, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { PluginConnectionsPanel } from "@/components/plugins/PluginConnectionsPanel";
import { PluginMembersPanel } from "@/components/plugins/PluginMembersPanel";
import { PluginPlacementPanel } from "@/components/plugins/PluginPlacementPanel";
import { PluginScopesPanel } from "@/components/plugins/PluginScopesPanel";
import { PluginSettingsPanel } from "@/components/plugins/PluginSettingsPanel";
import { PluginUpdatesPanel } from "@/components/plugins/PluginUpdatesPanel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useCommunities } from "@/hooks/useCommunities";
import { useCommunityPluginDetail } from "@/hooks/useCommunityPluginDetail";
import {
  useCommunityPlugins,
  useUninstallCommunityPlugin,
  useUninstallNotice,
  useUpdateCommunityPlugin,
} from "@/hooks/useCommunityPlugins";
import { useCommunityPath } from "@/lib/communityUrl";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDate } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { hasInitiativeSurfaces } from "@/lib/pluginSurfaces";
import { cn } from "@/lib/utils";

export function SettingsCommunityPluginsPage() {
  const { t } = useTranslation(["plugins", "common"]);
  const gp = useCommunityPath();
  const pluginsQuery = useCommunityPlugins();
  const { activeCommunity } = useCommunities();
  // Installing a plug-in, and the credentials that authorize the whole
  // community, are the seat's. Connecting your own account is not, and
  // happens from the plug-in itself rather than here.
  const holdsTheSeat = Boolean(activeCommunity?.can.seat);
  // Erasing a plug-in's data with it is for the community's own admins.
  const administers = Boolean(activeCommunity?.can.administer_content);
  const closed = Boolean(activeCommunity?.closed_surfaces?.includes("plugins"));

  const plugins = pluginsQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("plugins:manage.title")}</CardTitle>
        <CardDescription>{t("plugins:manage.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {closed && (
          <Alert>
            <AlertDescription>{t("plugins:manage.closed")}</AlertDescription>
          </Alert>
        )}
        {pluginsQuery.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : plugins.length ? (
          plugins.map((plugin) => (
            <PluginRow
              key={plugin.id}
              plugin={plugin}
              canManage={Boolean(holdsTheSeat)}
              canErase={holdsTheSeat && administers}
              closed={closed}
            />
          ))
        ) : (
          <div className="space-y-3 rounded-lg border border-dashed p-6 text-center">
            <p className="text-muted-foreground text-sm">{t("plugins:manage.empty")}</p>
            {holdsTheSeat && !closed && (
              <Button variant="outline" asChild>
                <Link to={gp("/marketplace")} search={{ kind: ListingKind.plugin }}>
                  <Store className="h-4 w-4" />
                  {t("plugins:manage.browse")}
                </Link>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * What this page reads off an install.
 *
 * Stated structurally rather than as the generated read: the configuration
 * fields are optional here, so the page is correct whether or not an install
 * reports them, and one row type serves both the list payload and the detail.
 */
export interface PluginListItem {
  id: number;
  name: string;
  enabled: boolean;
  created_at: string;
  needs_config?: boolean;
  config_state?: string;
  config_state_detail?: string | null;
  /** Provided by the platform: named as such, and not removable here. */
  mandatory?: boolean;
  /** False when the plug-in's service is not set up on this server. */
  available?: boolean;
}

function PluginRow({
  plugin,
  canManage,
  canErase,
  closed,
}: {
  plugin: PluginListItem;
  canManage: boolean;
  canErase: boolean;
  /** Plug-ins are managed by whoever runs the server, not here. */
  closed: boolean;
}) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const [name, setName] = useState(plugin.name);
  const [confirming, setConfirming] = useState(false);
  const [erase, setErase] = useState(false);
  const [open, setOpen] = useState(false);
  const update = useUpdateCommunityPlugin(plugin.id);
  const uninstall = useUninstallCommunityPlugin();
  const canChange = canManage && !closed;

  const save = (patch: { name?: string; enabled?: boolean }) =>
    update.mutate(patch, {
      onSuccess: () => toast.success(t("plugins:manage.saved")),
      onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
    });

  const remove = () =>
    uninstall.mutate(
      { pluginId: plugin.id, erase: canErase && erase },
      {
        onSuccess: () => {
          toast.success(t("plugins:manage.removed", { name: plugin.name }));
          setConfirming(false);
        },
        onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
      }
    );

  const confirm = (open: boolean) => {
    setConfirming(open);
    if (!open) setErase(false);
  };

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border">
      <div className="flex flex-wrap items-center gap-3 p-3">
        <Blocks className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1 space-y-1">
          {canChange ? (
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => name.trim() && name !== plugin.name && save({ name: name.trim() })}
              aria-label={t("plugins:manage.rename")}
              className="h-8 max-w-xs"
            />
          ) : (
            <p className="font-medium text-sm">{plugin.name}</p>
          )}
          <p className="text-muted-foreground text-xs">
            {t("plugins:manage.installed", {
              date: formatDate(plugin.created_at),
            })}
          </p>
        </div>

        {/* Unfinished configuration is the one thing worth surfacing on the
            collapsed row: it is why a plug-in looks installed and does nothing. */}
        {plugin.needs_config && (
          <Badge variant="outline" className="gap-1">
            <TriangleAlert className="h-3 w-3" aria-hidden />
            {t("plugins:manage.needsConfig")}
          </Badge>
        )}
        {plugin.config_state === "invalid" && (
          <Badge variant="destructive">
            {plugin.config_state_detail ?? t("plugins:manage.configInvalid")}
          </Badge>
        )}
        {/* Visible, so nobody wonders what it is — just not removable. */}
        {plugin.mandatory && (
          <Badge variant="secondary" className="gap-1">
            <ShieldCheck className="h-3 w-3" aria-hidden />
            {t("plugins:manage.provided")}
          </Badge>
        )}
        {plugin.available === false && (
          <Badge variant="outline">{t("plugins:manage.unavailable")}</Badge>
        )}
        {!plugin.enabled && <Badge variant="outline">{t("plugins:manage.disabled")}</Badge>}

        <div className="flex shrink-0 items-center gap-2">
          {/* A plug-in the platform provides has no switch and no remove button:
              the affordances are absent rather than present-and-refusing. */}
          {canChange && !plugin.mandatory && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => save({ enabled: !plugin.enabled })}
                disabled={update.isPending}
              >
                {update.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {plugin.enabled ? t("plugins:manage.disable") : t("plugins:manage.enable")}
              </Button>
              <Button size="sm" variant="destructive" onClick={() => confirm(true)}>
                {t("plugins:manage.remove")}
              </Button>
            </>
          )}
          <CollapsibleTrigger asChild>
            <Button size="sm" variant="ghost" aria-label={t("plugins:manage.configure")}>
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", !open && "-rotate-90")}
                aria-hidden
              />
            </Button>
          </CollapsibleTrigger>
        </div>
      </div>

      <CollapsibleContent>
        {/* Fetched only once opened: the detail read carries every connection's
            whole pinned form, which the collapsed list has no use for. */}
        {open && <PluginDetailPanels pluginId={plugin.id} canManage={canManage} closed={closed} />}
      </CollapsibleContent>

      <ConfirmDialog
        open={confirming}
        onOpenChange={confirm}
        title={t("plugins:manage.removeTitle", { name: plugin.name })}
        description={
          <>
            {t("plugins:manage.removeBody")}
            {confirming && (
              <RemovalNotice pluginId={plugin.id} locale={i18n.resolvedLanguage ?? i18n.language} />
            )}
          </>
        }
        confirmLabel={erase ? t("plugins:manage.removeAndErase") : t("plugins:manage.remove")}
        onConfirm={remove}
        isLoading={uninstall.isPending}
        destructive
      >
        {/* Removing keeps what the plug-in calls the community and its members,
            so installing it again picks up where it left off. Erasing is the
            community admins' separate choice. */}
        {canErase && (
          <div className="flex items-start gap-2">
            <Checkbox
              id={`erase-${plugin.id}`}
              checked={erase}
              onCheckedChange={(checked) => setErase(checked === true)}
              className="mt-0.5"
            />
            <div className="space-y-1">
              <Label htmlFor={`erase-${plugin.id}`}>{t("plugins:manage.erase")}</Label>
              <p className="text-muted-foreground text-xs">{t("plugins:manage.eraseHelp")}</p>
            </div>
          </div>
        )}
      </ConfirmDialog>
    </Collapsible>
  );
}

/**
 * What removing this plug-in means beyond the usual, when somebody other than
 * this server has a say in it: their own sentence, shown as they gave it, or a
 * neutral one when they did not answer in time. Nothing for any other plug-in.
 */
function RemovalNotice({ pluginId, locale }: { pluginId: number; locale: string }) {
  const { t } = useTranslation(["plugins"]);
  const notice = useUninstallNotice(pluginId, locale, true);
  const { activeCommunity } = useCommunities();
  const { canSell, openAddress } = useBillingPortal();
  const data = notice.data;
  if (!data?.managed) return null;
  const actionUrl = data.action_url;
  return (
    <span className="mt-2 block">
      {data.message ?? t("plugins:manage.removeManagedNeutral")}
      {actionUrl && canSell && activeCommunity && (
        <>
          {" "}
          <Button
            variant="link"
            className="h-auto p-0"
            onClick={() => void openAddress(activeCommunity.id, actionUrl)}
          >
            {t("plugins:manage.removeManagedAction")}
          </Button>
        </>
      )}
    </span>
  );
}

/**
 * The plug-in's connections, and — for the seat — its settings, where it appears
 * and who opens it there, what it can reach, who has connected to it and how it
 * takes new versions.
 */
function PluginDetailPanels({
  pluginId,
  canManage,
  closed,
}: {
  pluginId: number;
  canManage: boolean;
  closed: boolean;
}) {
  const { t } = useTranslation(["plugins", "common"]);
  const detail = useCommunityPluginDetail(pluginId);

  if (detail.isLoading) return <Skeleton className="m-3 h-24" />;
  if (!detail.data) return null;

  return (
    <div className="space-y-6 border-t p-4">
      <PluginConnectionsPanel
        pluginId={pluginId}
        connections={detail.data.connections}
        canManage={canManage}
        closed={closed}
      />

      {canManage && !closed && (
        <>
          <PluginSettingsPanel pluginId={pluginId} settings={detail.data.settings ?? []} />

          {/* Only a plug-in with an initiative surface has somewhere to place. */}
          {hasInitiativeSurfaces(detail.data.definition) && (
            <PluginPlacementPanel plugin={detail.data} />
          )}

          {(detail.data.requested_scopes ?? []).length > 0 && (
            <PluginScopesPanel plugin={detail.data} />
          )}
        </>
      )}

      {/* Revoking and blocking stay the seat's while the rest is closed. */}
      {canManage && (
        <section className="space-y-2">
          <h3 className="font-medium text-sm">{t("plugins:members.title")}</h3>
          <PluginMembersPanel pluginId={pluginId} enabled={canManage} />
        </section>
      )}

      {canManage && !closed && <PluginUpdatesPanel plugin={detail.data} />}
    </div>
  );
}
