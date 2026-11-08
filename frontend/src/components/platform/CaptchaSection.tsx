/**
 * Platform → Security: the captcha asked of anybody signing up, or asking for
 * an emailed sign-in code.
 *
 * Three values, and it is on only when all three are there. The secret is
 * write-only: the page is told whether one is stored, never what it is, so an
 * empty field keeps it.
 */

import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CaptchaSettingsUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useServerForm } from "@/hooks/useServerForm";
import { useCaptchaSettings, useUpdateCaptchaSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const PROVIDERS = ["hcaptcha", "turnstile", "recaptcha"] as const;
type Provider = (typeof PROVIDERS)[number];
const OFF = "off";

const isProvider = (value: string): value is Provider =>
  (PROVIDERS as readonly string[]).includes(value);

export const CaptchaSection = () => {
  const { t } = useTranslation("settings");
  const query = useCaptchaSettings();
  const form = useServerForm(
    query.data,
    (data) => ({
      provider: data?.provider ?? OFF,
      site_key: data?.site_key ?? "",
    }),
    "captcha"
  );
  // Never seeded — the server does not hand the secret back.
  const [secret, setSecret] = useState("");

  const update = useUpdateCaptchaSettings({
    onSuccess: () => {
      toast.success(t("captcha.saved"));
      setSecret("");
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:captcha.error")),
  });

  const saved = query.data;
  if (!saved) return null;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sent = form.values;
    const payload: CaptchaSettingsUpdate = {
      provider: isProvider(sent.provider) ? sent.provider : null,
      site_key: sent.site_key.trim() || null,
    };
    // Absent keeps the stored secret, so only a typed one is sent.
    if (secret) {
      payload.secret_key = secret;
    }
    update.mutate(payload, { onSuccess: () => form.settle(sent) });
  };

  return (
    <SettingsSection
      title={t("captcha.title")}
      description={t("captcha.description")}
      action={
        <Badge variant={saved.enforcing ? "default" : "secondary"}>
          {saved.enforcing ? t("captcha.on") : t("captcha.off")}
        </Badge>
      }
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        <Field label={t("captcha.providerLabel")}>
          <Select
            value={form.values.provider}
            onValueChange={(value) => {
              if (value === OFF || isProvider(value)) {
                form.set({ provider: value });
              }
            }}
          >
            <SelectTrigger className="w-full sm:w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={OFF}>{t("captcha.providers.off")}</SelectItem>
              {PROVIDERS.map((provider) => (
                <SelectItem key={provider} value={provider}>
                  {t(`captcha.providers.${provider}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <div className="grid grid-cols-pair gap-4">
          <Field label={t("captcha.siteKeyLabel")}>
            <Input
              value={form.values.site_key}
              onChange={(event) => form.set({ site_key: event.target.value })}
            />
          </Field>
          <Field label={t("captcha.secretKeyLabel")} hint={t("captcha.secretKeyHelp")}>
            <Input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              placeholder={saved.has_secret_key ? t("captcha.secretKeySet") : ""}
            />
          </Field>
        </div>
        {!saved.enforcing && form.values.provider !== OFF && (
          <p className="text-muted-foreground text-sm">{t("captcha.incomplete")}</p>
        )}
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? t("captcha.saving") : t("captcha.save")}
        </Button>
      </form>
    </SettingsSection>
  );
};
