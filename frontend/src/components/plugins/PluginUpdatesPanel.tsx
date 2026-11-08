/**
 * How one install takes new versions, and the button for when it does not.
 *
 * Automatic is where an install starts, so the switch here is the way *out* of
 * it rather than something to find and turn on. Turned off, the community reads
 * each version first and applies it with the button beside it — the same re-pin
 * the server's sweep would have done, asked for by hand.
 *
 * The button appears only when there is a version to move to, which the server
 * answers with `update_version`. An install already on the newest gets a plain
 * "Up to date" rather than a button whose only outcome is being told there was
 * nothing to do.
 *
 * A newer version this server cannot run (`update_refused`) is named with the
 * reason, rather than reading as "Up to date".
 *
 * A version that asks for more than the install holds — a new scope, or a new
 * surface inside initiatives — is not applied on its own. The server says what
 * it asks for in `pending_update`, and {@link PluginPendingUpdate} shows that
 * as "Version X wants to: …" with accept and decline. Accepting grants the new
 * scopes with the version; declining keeps the current version and stops the
 * asking until a newer one is published. The settings page draws it first in
 * the plug-in's settings, since it is what the seat came to answer.
 *
 * Community admins only — the caller decides that, since this renders inside a
 * section that has already made the call.
 */

import { isAxiosError } from "axios";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  CommunityPluginDetail,
  CommunityPluginUpgradeAsks,
} from "@/api/generated/initiativeAPI.schemas";
import { useDeclinePluginUpgrade, useUpgradePlugin } from "@/hooks/useCommunityPluginDetail";
import { useUpdateCommunityPlugin } from "@/hooks/useCommunityPlugins";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { type PluginNames, scopeSentence } from "@/lib/pluginScopes";
import { localized } from "@/lib/widgets/widgetMeta";
import { Button } from "@/ui/button";
import { Switch } from "@/ui/switch";

export function PluginUpdatesPanel({ plugin }: { plugin: CommunityPluginDetail }) {
  const { t } = useTranslation(["plugins", "common"]);
  const update = useUpdateCommunityPlugin(plugin.id);
  const upgrade = useUpgradePlugin(plugin.id);
  const pending = plugin.update_version ?? null;
  const asks = plugin.pending_update ?? null;
  const refused = plugin.update_refused ?? null;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-0.5">
          <p className="font-medium text-sm">{t("plugins:manage.autoUpdate")}</p>
          <p className="text-muted-foreground text-xs">{t("plugins:manage.autoUpdateHelp")}</p>
        </div>
        <Switch
          aria-label={t("plugins:manage.autoUpdate")}
          checked={plugin.auto_update}
          disabled={update.isPending}
          onCheckedChange={(checked) =>
            update.mutate(
              { auto_update: checked },
              {
                onSuccess: () =>
                  toast.success(
                    checked ? t("plugins:manage.autoUpdateOn") : t("plugins:manage.autoUpdateOff")
                  ),
                onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
              }
            )
          }
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">
          {t("plugins:manage.version", { version: plugin.listing_version })}
        </span>
        {asks ? null : pending ? (
          <Button
            size="sm"
            variant="outline"
            disabled={upgrade.isPending}
            onClick={() =>
              upgrade.mutate(undefined, {
                onSuccess: (updated) =>
                  toast.success(t("plugins:manage.upgraded", { version: updated.listing_version })),
                onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
              })
            }
          >
            {upgrade.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("plugins:manage.upgradeTo", { version: pending })}
          </Button>
        ) : refused ? (
          <span className="text-muted-foreground text-xs">
            {t("plugins:updates.refused", { version: refused.version })}{" "}
            {messageForCode(refused.reason, "plugins:error")}
          </span>
        ) : (
          <span className="text-muted-foreground text-xs">{t("plugins:manage.upToDate")}</span>
        )}
      </div>
    </section>
  );
}

/** "Version X wants to: …", with the seat's accept and decline. */
export function PluginPendingUpdate({
  pluginId,
  asks,
  pluginNames,
}: {
  pluginId: number;
  asks: CommunityPluginUpgradeAsks;
  pluginNames?: PluginNames;
}) {
  const { t, i18n } = useTranslation(["plugins", "common", "nav"]);
  const upgrade = useUpgradePlugin(pluginId);
  const decline = useDeclinePluginUpgrade(pluginId);
  const busy = upgrade.isPending || decline.isPending;

  /** A refusal because the offer moved says so; the panel then refreshes. */
  const failed = (error: unknown) => {
    const moved = isAxiosError(error) && error.response?.status === 409;
    toast.error(moved ? t("plugins:updates.moved") : getErrorMessage(error, "plugins:error"));
  };

  const accept = () =>
    upgrade.mutate(
      { version: asks.version, add_scopes: asks.added_scopes },
      {
        onSuccess: (updated) =>
          toast.success(t("plugins:manage.upgraded", { version: updated.listing_version })),
        onError: failed,
      }
    );

  const refuse = () =>
    decline.mutate(asks.version, {
      onSuccess: () => toast.success(t("plugins:updates.declinedDone", { version: asks.version })),
      onError: failed,
    });

  return (
    <div className="space-y-2 rounded-md border p-3">
      <p className="font-medium text-sm">{t("plugins:updates.wants", { version: asks.version })}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {asks.added_scopes.map((scope) => (
          <li key={scope}>{scopeSentence(scope, t, pluginNames)}</li>
        ))}
        {asks.added_surfaces.map((surface) => (
          <li key={surface.id}>
            {t("plugins:updates.newSurface", {
              name: localized(surface.name, i18n.language) ?? surface.id,
            })}
          </li>
        ))}
      </ul>
      {asks.declined && (
        <p className="text-muted-foreground text-xs">
          {t("plugins:updates.declined", { version: asks.version })}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={accept}>
          {upgrade.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("plugins:updates.accept")}
        </Button>
        {!asks.declined && (
          <Button size="sm" variant="outline" disabled={busy} onClick={refuse}>
            {decline.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("plugins:updates.decline")}
          </Button>
        )}
      </div>
    </div>
  );
}
