/**
 * Platform → Integrations: the marketplace registry.
 *
 * One switch (follow the registry or not), where it stands (when it last
 * updated, how many listings it brought, why the last attempt stopped), a
 * "refresh now", and an upload for a server that cannot reach the registry.
 * Everything here is `config.manage`.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { RegistryRefreshRead } from "@/api/generated/initiativeAPI.schemas";
import { useReadRegistryStatus } from "@/api/generated/marketplace/marketplace";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import {
  useRefreshRegistry,
  useUpdateRegistrySettings,
  useUploadRegistryBundle,
} from "@/hooks/useMarketplaceRegistry";
import { messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { FileDropArea } from "@/ui/file-drop";
import { formatDateTime } from "@/ui/lib/formatDate";
import { Switch } from "@/ui/switch";

/** What the status row records for an uploaded bundle. */
const BUNDLE_SOURCE = "bundle";

export const MarketplaceRegistrySection = () => {
  const { t } = useTranslation("settings");
  const status = useReadRegistryStatus();
  const [bundle, setBundle] = useState<File | null>(null);

  const reportApplied = (result: RegistryRefreshRead, key: "refreshed" | "bundleApplied") => {
    toast.success(t(`marketplaceRegistry.${key}`, { count: result.upserted }));
    if (result.skipped.length > 0) {
      toast.warning(t("marketplaceRegistry.skipped", { count: result.skipped.length }));
    }
  };

  const update = useUpdateRegistrySettings({
    onSuccess: (result) =>
      toast.success(
        result.enabled
          ? t("marketplaceRegistry.enabledToast")
          : t("marketplaceRegistry.disabledToast")
      ),
  });
  const refresh = useRefreshRegistry({
    onSuccess: (result) => reportApplied(result, "refreshed"),
  });
  const upload = useUploadRegistryBundle({
    onSuccess: (result) => {
      reportApplied(result, "bundleApplied");
      setBundle(null);
    },
  });

  const state = status.data;
  if (!state) return null;

  const stale = state.expires_at !== null && new Date(state.expires_at).getTime() < Date.now();
  const busy = update.isPending || refresh.isPending || upload.isPending;

  return (
    <SettingsSection
      title={t("marketplaceRegistry.title")}
      description={t("marketplaceRegistry.description")}
    >
      {!state.configured ? (
        <p className="text-muted-foreground text-sm">{t("marketplaceRegistry.notConfigured")}</p>
      ) : (
        <>
          <SettingsRow
            label={t("marketplaceRegistry.toggleLabel")}
            description={t("marketplaceRegistry.toggleHelp")}
          >
            <Switch
              checked={state.enabled}
              disabled={busy}
              onCheckedChange={(checked) => update.mutate({ enabled: Boolean(checked) })}
            />
          </SettingsRow>

          <div className="space-y-1 text-sm">
            <p className="break-all text-muted-foreground">
              {t("marketplaceRegistry.registryUrl", { url: state.registry_url })}
            </p>
            {state.custom_root ? (
              <p className="text-muted-foreground">{t("marketplaceRegistry.customRoot")}</p>
            ) : null}
            <p>
              {state.last_success_at
                ? t("marketplaceRegistry.lastSuccess", {
                    when: formatDateTime(state.last_success_at),
                  })
                : t("marketplaceRegistry.neverUpdated")}{" "}
              {t("marketplaceRegistry.listingCount", { count: state.listing_count })}
            </p>
            {state.last_source === BUNDLE_SOURCE ? (
              <p className="text-muted-foreground">{t("marketplaceRegistry.fromBundle")}</p>
            ) : null}
            {stale && state.expires_at ? (
              <p className="text-amber-600 dark:text-amber-400">
                {t("marketplaceRegistry.stale", { when: formatDateTime(state.expires_at) })}
              </p>
            ) : null}
            {state.last_error ? (
              <p className="text-destructive">
                {t("marketplaceRegistry.lastError", {
                  reason: messageForCode(
                    state.last_error,
                    "settings:marketplaceRegistry.lastErrorFallback"
                  ),
                })}
              </p>
            ) : null}
          </div>

          <Button
            type="button"
            variant="outline"
            disabled={busy || !state.enabled}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending
              ? t("marketplaceRegistry.refreshing")
              : t("marketplaceRegistry.refresh")}
          </Button>

          <div className="space-y-2 border-t pt-4">
            <p className="text-muted-foreground text-sm">{t("marketplaceRegistry.bundleHelp")}</p>
            <FileDropArea
              accept=".tar,.tgz,.tar.gz,application/gzip,application/x-tar"
              onFile={setBundle}
              prompt={bundle ? bundle.name : t("marketplaceRegistry.bundleLabel")}
            />
            <Button
              type="button"
              variant="outline"
              disabled={busy || bundle === null}
              onClick={() => bundle && upload.mutate(bundle)}
            >
              {upload.isPending
                ? t("marketplaceRegistry.bundleUploading")
                : t("marketplaceRegistry.bundleUpload")}
            </Button>
          </div>
        </>
      )}
    </SettingsSection>
  );
};
