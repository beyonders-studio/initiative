/**
 * Platform → Push notifications: the Firebase project the mobile apps register
 * with and the server sends through.
 *
 * Four public values the app fetches at launch, and a service-account key the
 * server keeps to itself. Whether a notification may reach a phone at all is a
 * separate answer, on Security.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PushSettingsUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { usePushSettings, useUpdatePushSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";

const TEXT_FIELDS = ["project_id", "application_id", "api_key", "sender_id"] as const;

/** Whether pasted text is one JSON object, which is what Firebase's key file is. */
const isJsonObject = (text: string): boolean => {
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
  } catch {
    return false;
  }
};

export const SettingsPushPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const query = usePushSettings({ enabled: canManagePlatformConfig });
  const form = useServerForm(
    query.data,
    (data) => ({
      enabled: data?.enabled ?? false,
      project_id: data?.project_id ?? "",
      application_id: data?.application_id ?? "",
      api_key: data?.api_key ?? "",
      sender_id: data?.sender_id ?? "",
    }),
    "push"
  );
  // Never seeded — the server does not hand the key back.
  const [serviceAccount, setServiceAccount] = useState("");
  const serviceAccountInvalid = serviceAccount.trim() !== "" && !isJsonObject(serviceAccount);

  const update = useUpdatePushSettings({
    onSuccess: () => {
      toast.success(t("push.saved"));
      setServiceAccount("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:push.error")),
  });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("push.platformOnly")}</p>;
  }

  if (query.isLoading) {
    return (
      <SkeletonRegion label={t("push.loading")}>
        <FormSkeleton fields={5} />
      </SkeletonRegion>
    );
  }

  if (query.isError || !query.data) {
    return <p className="text-destructive text-sm">{t("push.loadError")}</p>;
  }

  const hasServiceAccount = query.data.has_service_account;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (serviceAccountInvalid) return;
    const sent = form.values;
    const payload: PushSettingsUpdate = {
      enabled: sent.enabled,
      project_id: sent.project_id.trim() || null,
      application_id: sent.application_id.trim() || null,
      api_key: sent.api_key.trim() || null,
      sender_id: sent.sender_id.trim() || null,
    };
    // Absent keeps the stored key, so only a pasted one is sent.
    if (serviceAccount.trim()) {
      payload.service_account_json = serviceAccount.trim();
    }
    update.mutate(payload, { onSuccess: () => form.settle(sent) });
  };

  return (
    <SettingsSection title={t("push.title")} description={t("push.description")}>
      <form className="space-y-6" onSubmit={handleSubmit}>
        <div className="flex items-start justify-between gap-4 rounded-md border px-4 py-3">
          <div className="space-y-1">
            <Label htmlFor="push-enabled" className="font-medium">
              {t("push.enabledLabel")}
            </Label>
            <p className="text-muted-foreground text-sm">{t("push.enabledHelp")}</p>
          </div>
          <Switch
            id="push-enabled"
            checked={form.values.enabled}
            onCheckedChange={(checked) => form.set({ enabled: Boolean(checked) })}
          />
        </div>

        <div className="grid grid-cols-pair gap-4">
          {TEXT_FIELDS.map((field) => (
            <div key={field} className="space-y-2">
              <Label htmlFor={`push-${field}`}>{t(`push.fields.${field}.label`)}</Label>
              <Input
                id={`push-${field}`}
                value={form.values[field]}
                onChange={(event) => form.set({ [field]: event.target.value })}
              />
              <p className="text-muted-foreground text-xs">{t(`push.fields.${field}.help`)}</p>
            </div>
          ))}
        </div>

        <Field
          label={t("push.serviceAccountLabel")}
          hint={!serviceAccountInvalid && t("push.serviceAccountHelp")}
          error={serviceAccountInvalid && t("push.serviceAccountInvalid")}
        >
          <Textarea
            rows={6}
            spellCheck={false}
            autoComplete="off"
            className="font-mono text-xs"
            value={serviceAccount}
            onChange={(event) => setServiceAccount(event.target.value)}
            placeholder={hasServiceAccount ? t("push.serviceAccountSet") : ""}
          />
        </Field>

        <Button type="submit" disabled={update.isPending || serviceAccountInvalid}>
          {update.isPending ? t("push.saving") : t("push.save")}
        </Button>
      </form>
    </SettingsSection>
  );
};
