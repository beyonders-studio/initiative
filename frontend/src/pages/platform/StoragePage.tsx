import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { StorageSettingsUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import {
  useStartStorageBackfill,
  useStorageBackfillStatus,
  useStorageSettings,
  useTestStorageConnection,
  useUpdateStorageSettings,
} from "@/hooks/useSettings";
import { messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Alert, AlertDescription, AlertTitle } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

type Backend = "local" | "s3";

const DEFAULT_STATE = {
  backend: "local" as Backend,
  s3_bucket: "",
  s3_region: "us-east-1",
  s3_endpoint_url: "",
  s3_access_key_id: "",
  s3_use_path_style: false,
  s3_local_fallback: false,
};

export const StoragePage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const storageQuery = useStorageSettings({ enabled: canManagePlatformConfig });
  // A bucket, a region, an endpoint and a key are typed in one at a time and
  // saved together, so a refetch part-way through must leave them alone.
  const form = useServerForm(
    storageQuery.data,
    (data) => ({
      backend: data?.backend === "s3" ? "s3" : DEFAULT_STATE.backend,
      s3_bucket: data?.s3_bucket ?? DEFAULT_STATE.s3_bucket,
      s3_region: data?.s3_region ?? DEFAULT_STATE.s3_region,
      s3_endpoint_url: data?.s3_endpoint_url ?? DEFAULT_STATE.s3_endpoint_url,
      s3_access_key_id: data?.s3_access_key_id ?? DEFAULT_STATE.s3_access_key_id,
      s3_use_path_style: data?.s3_use_path_style ?? DEFAULT_STATE.s3_use_path_style,
      s3_local_fallback: data?.s3_local_fallback ?? DEFAULT_STATE.s3_local_fallback,
    }),
    "storage"
  );
  // Never seeded — the server does not hand the secret back.
  const [secret, setSecret] = useState("");
  const hasSecret = storageQuery.data?.has_secret_access_key ?? false;

  const backfillStatus = useStorageBackfillStatus({
    enabled: canManagePlatformConfig,
    // Poll while a run is in flight; idle otherwise.
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
  const isBackfilling = backfillStatus.data?.status === "running";

  const buildPayload = (): StorageSettingsUpdate => {
    const payload: StorageSettingsUpdate = {
      backend: form.values.backend,
      s3_bucket: form.values.s3_bucket || null,
      s3_region: form.values.s3_region || "us-east-1",
      s3_endpoint_url: form.values.s3_endpoint_url || null,
      s3_access_key_id: form.values.s3_access_key_id || null,
      s3_use_path_style: form.values.s3_use_path_style,
      s3_local_fallback: form.values.s3_local_fallback,
    };
    // Only send the secret when the owner typed one, so an empty field keeps the
    // stored key (the backend treats "field absent" as "unchanged").
    if (secret) {
      payload.s3_secret_access_key = secret;
    }
    return payload;
  };

  const updateMutation = useUpdateStorageSettings({
    onSuccess: () => {
      toast.success(t("storage.saveSuccess"));
      setSecret("");
    },
    onError: () => toast.error(t("storage.saveError")),
  });

  const testMutation = useTestStorageConnection({
    onSuccess: (result) => {
      if (result.success) {
        toast.success(result.message || t("storage.testSuccess"));
      } else {
        toast.error(messageForCode(result.message, "settings:storage.testError"));
      }
    },
    onError: () => toast.error(t("storage.testError")),
  });

  const backfillMutation = useStartStorageBackfill({
    onSuccess: () => {
      toast.success(t("storage.backfillStarted"));
      void backfillStatus.refetch();
    },
    onError: () => toast.error(t("storage.backfillError")),
  });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("storage.platformOnly")}</p>;
  }

  if (storageQuery.isLoading) {
    return (
      <SkeletonRegion>
        <FormSkeleton fields={3} />
      </SkeletonRegion>
    );
  }

  if (storageQuery.isError || !storageQuery.data) {
    return <StatusMessage onRetry={storageQuery.refetch} />;
  }

  const isS3 = form.values.backend === "s3";
  // The backfill copies into the bucket the server is saved to use, so it waits
  // for S3 to be saved, not merely chosen in the form.
  const backfillReady = storageQuery.data.backend === "s3" && Boolean(storageQuery.data.s3_bucket);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sent = form.values;
    updateMutation.mutate(buildPayload(), { onSuccess: () => form.settle(sent) });
  };

  return (
    <SettingsSection title={t("storage.title")} description={t("storage.description")}>
      <form className="space-y-6" onSubmit={handleSubmit}>
        <Field label={t("storage.backendLabel")} hint={t("storage.backendHelp")}>
          <Select
            value={form.values.backend}
            onValueChange={(value) => {
              // Guard against a stray empty value (Radix can emit one during
              // mount in jsdom); only accept the two real backends.
              if (value === "local" || value === "s3") {
                form.set({ backend: value });
              }
            }}
          >
            <SelectTrigger className="w-full sm:w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="local">{t("storage.backendLocal")}</SelectItem>
              <SelectItem value="s3">{t("storage.backendS3")}</SelectItem>
            </SelectContent>
          </Select>
        </Field>

        {isS3 && (
          <>
            <Alert>
              <AlertTitle>{t("storage.cutoverTitle")}</AlertTitle>
              <AlertDescription>{t("storage.cutoverHelp")}</AlertDescription>
            </Alert>

            <div className="grid grid-cols-pair gap-4">
              <Field label={t("storage.bucketLabel")}>
                <Input
                  value={form.values.s3_bucket}
                  onChange={(event) => form.set({ s3_bucket: event.target.value })}
                  placeholder={t("storage.bucketPlaceholder")}
                />
              </Field>
              <Field label={t("storage.regionLabel")}>
                <Input
                  value={form.values.s3_region}
                  onChange={(event) => form.set({ s3_region: event.target.value })}
                  placeholder="us-east-1"
                />
              </Field>
            </div>

            <Field label={t("storage.endpointLabel")} hint={t("storage.endpointHelp")}>
              <Input
                value={form.values.s3_endpoint_url}
                onChange={(event) => form.set({ s3_endpoint_url: event.target.value })}
                placeholder={t("storage.endpointPlaceholder")}
              />
            </Field>

            <div className="grid grid-cols-pair gap-4">
              <Field label={t("storage.accessKeyLabel")}>
                <Input
                  value={form.values.s3_access_key_id}
                  onChange={(event) => form.set({ s3_access_key_id: event.target.value })}
                  placeholder={t("storage.accessKeyPlaceholder")}
                />
              </Field>
              <Field label={t("storage.secretKeyLabel")} hint={t("storage.secretKeyHelp")}>
                <Input
                  type="password"
                  value={secret}
                  onChange={(event) => setSecret(event.target.value)}
                  placeholder={hasSecret ? t("storage.secretKeySet") : ""}
                />
              </Field>
            </div>

            <div className="space-y-4">
              <SettingsRow
                label={t("storage.pathStyleLabel")}
                description={t("storage.pathStyleHelp")}
              >
                <Switch
                  checked={form.values.s3_use_path_style}
                  onCheckedChange={(checked) => form.set({ s3_use_path_style: Boolean(checked) })}
                />
              </SettingsRow>
              <SettingsRow
                label={t("storage.localFallbackLabel")}
                description={t("storage.localFallbackHelp")}
              >
                <Switch
                  checked={form.values.s3_local_fallback}
                  onCheckedChange={(checked) => form.set({ s3_local_fallback: Boolean(checked) })}
                />
              </SettingsRow>
            </div>
          </>
        )}

        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? t("storage.saving") : t("storage.save")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => testMutation.mutate(buildPayload())}
            disabled={testMutation.isPending || !isS3}
          >
            {testMutation.isPending ? t("storage.testing") : t("storage.testConnection")}
          </Button>
        </div>
      </form>

      <div className="mt-8 space-y-3 border-t pt-6">
        <div>
          <h3 className="font-medium">{t("storage.backfillTitle")}</h3>
          <p className="text-muted-foreground text-sm">{t("storage.backfillHelp")}</p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => backfillMutation.mutate()}
          disabled={!backfillReady || backfillMutation.isPending || isBackfilling}
        >
          {isBackfilling ? t("storage.backfillRunning") : t("storage.startBackfill")}
        </Button>
        {backfillStatus.data && backfillStatus.data.status !== "idle" && (
          <div className="rounded-md border px-4 py-3 text-sm">
            <p className="font-medium">
              {t(`storage.backfillStatus.${backfillStatus.data.status}`)}
            </p>
            <p className="text-muted-foreground">
              {t("storage.backfillCounts", {
                copied: backfillStatus.data.copied,
                skipped: backfillStatus.data.skipped,
                failed: backfillStatus.data.failed,
              })}
            </p>
            {backfillStatus.data.error && (
              <p className="text-destructive">
                {messageForCode(
                  backfillStatus.data.error,
                  "errors:SETTINGS_STORAGE_BACKFILL_FAILED"
                )}
              </p>
            )}
          </div>
        )}
      </div>
    </SettingsSection>
  );
};
