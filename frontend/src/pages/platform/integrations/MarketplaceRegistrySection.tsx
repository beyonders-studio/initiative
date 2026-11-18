/**
 * Platform → Integrations: the plug-in registry.
 *
 * One row while the server gets updates from the registry: the switch, when it
 * last updated and how many listings it holds, and Refresh now beside the
 * switch. With updates off, Refresh gives way to a registry bundle, for a
 * server that cannot reach the registry; a bundle applies as soon as it is
 * dropped. A failed update or expired signatures add a line only while true.
 * Everything here is `config.manage`.
 */

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
    onSuccess: (result) => reportApplied(result, "bundleApplied"),
  });

  const state = status.data;
  if (!state) return null;

  const stale = state.expires_at !== null && new Date(state.expires_at).getTime() < Date.now();
  const busy = update.isPending || refresh.isPending || upload.isPending;

  const updated = state.last_success_at
    ? t(
        state.last_source === BUNDLE_SOURCE
          ? "marketplaceRegistry.updatedFromBundle"
          : "marketplaceRegistry.updated",
        { when: formatDateTime(state.last_success_at) }
      )
    : t("marketplaceRegistry.neverUpdated");
  const summary = `${updated} · ${t("marketplaceRegistry.listingCount", { count: state.listing_count })}`;

  return (
    <SettingsSection
      title={t("marketplaceRegistry.title")}
      description={t("marketplaceRegistry.description")}
    >
      {!state.configured ? (
        <p className="text-muted-foreground text-sm">{t("marketplaceRegistry.notConfigured")}</p>
      ) : (
        <SettingsRow
          label={t("marketplaceRegistry.toggleLabel")}
          description={state.enabled ? summary : t("marketplaceRegistry.updatesOff")}
          below={
            <>
              {state.enabled ? null : (
                <div className="space-y-2">
                  <FileDropArea
                    accept=".tar,.tgz,.tar.gz,application/gzip,application/x-tar"
                    onFile={(file) => upload.mutate(file)}
                    prompt={
                      upload.isPending
                        ? t("marketplaceRegistry.bundleUploading")
                        : t("marketplaceRegistry.bundleLabel")
                    }
                    disabled={busy}
                  />
                  {state.last_success_at ? (
                    <p className="text-muted-foreground text-sm">{summary}</p>
                  ) : null}
                </div>
              )}
              {state.custom_root ? (
                <p className="text-muted-foreground text-sm">
                  {t("marketplaceRegistry.customRoot")}
                </p>
              ) : null}
              {stale && state.expires_at ? (
                <p className="text-amber-600 text-sm dark:text-amber-400">
                  {t("marketplaceRegistry.stale", { when: formatDateTime(state.expires_at) })}
                </p>
              ) : null}
              {state.last_error ? (
                <p className="text-destructive text-sm">
                  {t("marketplaceRegistry.lastError", {
                    reason: messageForCode(
                      state.last_error,
                      "settings:marketplaceRegistry.lastErrorFallback"
                    ),
                  })}
                </p>
              ) : null}
            </>
          }
        >
          {state.enabled ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => refresh.mutate()}
            >
              {refresh.isPending
                ? t("marketplaceRegistry.refreshing")
                : t("marketplaceRegistry.refresh")}
            </Button>
          ) : null}
          <Switch
            checked={state.enabled}
            disabled={busy}
            onCheckedChange={(checked) => update.mutate({ enabled: Boolean(checked) })}
          />
        </SettingsRow>
      )}
    </SettingsSection>
  );
};
