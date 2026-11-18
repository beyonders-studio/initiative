/**
 * Platform → Integrations: the plug-in registry.
 *
 * One row while the server gets updates from the registry: the switch, when it
 * last updated and how many listings it holds, and Refresh now beside the
 * switch. With updates off, Refresh gives way to a registry bundle, for a
 * server that cannot reach the registry; a bundle applies as soon as it is
 * dropped. What the last update skipped, expired signatures or a failed update
 * add a line only while true.
 * Everything here is `config.manage`.
 */

import { useTranslation } from "react-i18next";

import type {
  RegistryRefreshRead,
  RegistrySkippedListing,
} from "@/api/generated/initiativeAPI.schemas";
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

/** Why one thing was skipped, in the operator's words. */
const skipReason = (item: RegistrySkippedListing): string =>
  messageForCode(item.code, "settings:marketplaceRegistry.skippedReasonFallback");

/** The name a skipped thing is shown under: never a path, a uid or a code. */
const skipName = (item: RegistrySkippedListing): string | null =>
  item.listing_name ?? item.publisher_name ?? null;

export const MarketplaceRegistrySection = () => {
  const { t } = useTranslation("settings");
  const status = useReadRegistryStatus();

  const reportApplied = (result: RegistryRefreshRead, key: "refreshed" | "bundleApplied") => {
    toast.success(t(`marketplaceRegistry.${key}`, { count: result.upserted }));
    const [only] = result.skipped;
    if (result.skipped.length === 1 && only.listing_name) {
      toast.warning(
        t("marketplaceRegistry.skippedListingToast", {
          listing: only.listing_name,
          reason: skipReason(only),
        })
      );
      return;
    }
    const names = [
      ...new Set(result.skipped.map(skipName).filter((name): name is string => !!name)),
    ];
    if (names.length > 0) {
      toast.warning(t("marketplaceRegistry.skippedNamed", { names: names.join(", ") }));
    } else if (result.skipped.length > 0) {
      toast.warning(t("marketplaceRegistry.skipped", { count: result.skipped.length }));
    }
  };

  const skipLine = (item: RegistrySkippedListing): string => {
    const reason = skipReason(item);
    if (item.listing_name) {
      return t("marketplaceRegistry.skippedListing", { listing: item.listing_name, reason });
    }
    if (item.publisher_name) {
      return t("marketplaceRegistry.skippedPublisher", {
        publisher: item.publisher_name,
        reason,
      });
    }
    return t("marketplaceRegistry.skippedUnnamed", { reason });
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
              {state.skipped.length > 0 ? (
                <div className="text-destructive text-sm">
                  <p>{t("marketplaceRegistry.skippedHeading")}</p>
                  <ul className="list-disc space-y-1 ps-5">
                    {state.skipped.map((item, index) => (
                      // biome-ignore lint/suspicious/noArrayIndexKey: a skip has no id, and the list is replaced whole
                      <li key={index}>{skipLine(item)}</li>
                    ))}
                  </ul>
                </div>
              ) : state.last_error ? (
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
