import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import { useEmailSettings, useSendTestEmail, useUpdateEmailSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { FormSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";
import { Switch } from "@/ui/switch";

interface EmailPayload {
  host?: string | null;
  port?: number | null;
  secure: boolean;
  reject_unauthorized: boolean;
  username?: string | null;
  password?: string | null;
  from_address?: string | null;
  test_recipient?: string | null;
}

const DEFAULT_STATE = {
  host: "",
  port: "",
  secure: false,
  reject_unauthorized: true,
  username: "",
  from_address: "",
};

export const SettingsEmailPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManagePlatformConfig = hasCapability(user, Capability.configManage);
  const emailQuery = useEmailSettings({ enabled: canManagePlatformConfig });
  // A server's address and credentials are typed in a few fields at a time and
  // saved at the end, so a refetch mid-way must leave them where they are.
  const form = useServerForm(
    emailQuery.data,
    (settings) => ({
      host: settings?.host ?? DEFAULT_STATE.host,
      port: settings?.port ? String(settings.port) : DEFAULT_STATE.port,
      secure: settings?.secure ?? DEFAULT_STATE.secure,
      reject_unauthorized: settings?.reject_unauthorized ?? DEFAULT_STATE.reject_unauthorized,
      username: settings?.username ?? DEFAULT_STATE.username,
      from_address: settings?.from_address ?? DEFAULT_STATE.from_address,
      test_recipient: settings?.test_recipient ?? "",
    }),
    "email"
  );
  // Never seeded — the server does not hand a password back, so this field is
  // write-only and empty means "leave it as it is".
  const [password, setPassword] = useState("");

  const updateMutation = useUpdateEmailSettings({
    onSuccess: () => {
      toast.success(t("email.saveSuccess"));
      setPassword("");
    },
    onError: () => toast.error(t("email.saveError")),
  });

  const testMutation = useSendTestEmail({
    onSuccess: () => toast.success(t("email.testSuccess")),
    onError: () => toast.error(t("email.testError")),
  });

  if (!canManagePlatformConfig) {
    return <p className="text-muted-foreground text-sm">{t("email.platformOnly")}</p>;
  }

  if (emailQuery.isLoading) {
    return (
      <SkeletonRegion>
        <FormSkeleton fields={5} />
      </SkeletonRegion>
    );
  }

  if (emailQuery.isError || !emailQuery.data) {
    return <StatusMessage onRetry={emailQuery.refetch} />;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // What is being sent, so anything typed while this is in flight is not
    // counted as saved by it.
    const sent = form.values;
    const payload: EmailPayload = {
      host: sent.host || null,
      port: sent.port ? Number(sent.port) : null,
      secure: sent.secure,
      reject_unauthorized: sent.reject_unauthorized,
      username: sent.username || null,
      from_address: sent.from_address || null,
      test_recipient: sent.test_recipient || null,
    };
    if (password) {
      payload.password = password;
    }
    updateMutation.mutate(payload, { onSuccess: () => form.settle(sent) });
  };

  return (
    <SettingsSection title={t("email.title")}>
      <form className="space-y-6" onSubmit={handleSubmit}>
        <div className="grid grid-cols-pair gap-4">
          <Field label={t("email.hostLabel")}>
            <Input
              value={form.values.host}
              onChange={(event) => form.set({ host: event.target.value })}
              placeholder={t("email.hostPlaceholder")}
            />
          </Field>
          <Field label={t("email.portLabel")}>
            <Input
              type="number"
              min={1}
              max={65535}
              value={form.values.port}
              onChange={(event) => form.set({ port: event.target.value })}
              placeholder={t("email.portPlaceholder")}
            />
          </Field>
        </div>
        <div className="space-y-4">
          <SettingsRow label={t("email.secureLabel")} description={t("email.secureHelp")}>
            <Switch
              checked={form.values.secure}
              onCheckedChange={(checked) => form.set({ secure: Boolean(checked) })}
            />
          </SettingsRow>
          <SettingsRow
            label={t("email.rejectUnauthorizedLabel")}
            description={t("email.rejectUnauthorizedHelp")}
          >
            <Switch
              checked={form.values.reject_unauthorized}
              onCheckedChange={(checked) => form.set({ reject_unauthorized: Boolean(checked) })}
            />
          </SettingsRow>
        </div>
        <div className="grid grid-cols-pair gap-4">
          <Field label={t("email.usernameLabel")}>
            <Input
              value={form.values.username}
              onChange={(event) => form.set({ username: event.target.value })}
            />
          </Field>
          <Field label={t("email.passwordLabel")} hint={t("email.passwordHelp")}>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={emailQuery.data.has_password ? t("email.passwordPlaceholder") : ""}
            />
          </Field>
        </div>
        <Field label={t("email.fromAddressLabel")}>
          <Input
            value={form.values.from_address}
            onChange={(event) => form.set({ from_address: event.target.value })}
            placeholder={t("email.fromAddressPlaceholder")}
          />
        </Field>
        <div className="grid grid-cols-pair gap-4">
          <Field label={t("email.testRecipientLabel")}>
            <Input
              type="email"
              value={form.values.test_recipient}
              onChange={(event) => form.set({ test_recipient: event.target.value })}
              placeholder={t("email.testRecipientPlaceholder")}
            />
          </Field>
          <div className="flex items-end">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => testMutation.mutate({ recipient: form.values.test_recipient || null })}
              disabled={testMutation.isPending}
            >
              {testMutation.isPending ? t("email.sendingTest") : t("email.sendTest")}
            </Button>
          </div>
        </div>
        <Button type="submit" disabled={updateMutation.isPending}>
          {updateMutation.isPending ? t("email.saving") : t("email.save")}
        </Button>
      </form>
    </SettingsSection>
  );
};
