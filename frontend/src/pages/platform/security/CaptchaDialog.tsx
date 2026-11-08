import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type {
  CaptchaSettingsResponse,
  CaptchaSettingsUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { useServerForm } from "@/hooks/useServerForm";
import { useUpdateCaptchaSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import type { RuleDialogProps } from "./ruleDialog";

const CAPTCHA_PROVIDERS = ["hcaptcha", "turnstile", "recaptcha"] as const;

type CaptchaProvider = (typeof CAPTCHA_PROVIDERS)[number];

const NO_CAPTCHA = "off";

const isCaptchaProvider = (value: string): value is CaptchaProvider =>
  (CAPTCHA_PROVIDERS as readonly string[]).includes(value);

/**
 * The captcha asked of anybody signing up, or asking for an emailed sign-in
 * code. Three values, and it is on only when all three are there. The secret
 * is write-only: the page is told whether one is stored, never what it is, so
 * an empty field keeps it.
 */
export const CaptchaDialog = ({
  saved,
  open,
  onOpenChange,
}: RuleDialogProps & { saved: CaptchaSettingsResponse }) => {
  const { t } = useTranslation(["settings", "common"]);
  const form = useServerForm(
    saved,
    (data) => ({
      provider: data?.provider ?? NO_CAPTCHA,
      site_key: data?.site_key ?? "",
      // Never seeded: the server does not hand the secret back.
      secret: "",
    }),
    open
  );
  const update = useUpdateCaptchaSettings({
    onSuccess: () => {
      toast.success(t("captcha.saved"));
      onOpenChange(false);
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const { provider, site_key, secret } = form.values;
    const payload: CaptchaSettingsUpdate = {
      provider: isCaptchaProvider(provider) ? provider : null,
      site_key: site_key.trim() || null,
    };
    // Absent keeps the stored secret, so only a typed one is sent.
    if (secret) {
      payload.secret_key = secret;
    }
    update.mutate(payload);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("captcha.title")}</DialogTitle>
          <DialogDescription>{t("captcha.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <Field label={t("captcha.providerLabel")}>
            <Select
              value={form.values.provider}
              onValueChange={(value) => {
                if (value === NO_CAPTCHA || isCaptchaProvider(value)) {
                  form.set({ provider: value });
                }
              }}
            >
              <SelectTrigger className="w-full sm:w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_CAPTCHA}>{t("captcha.providers.off")}</SelectItem>
                {CAPTCHA_PROVIDERS.map((provider) => (
                  <SelectItem key={provider} value={provider}>
                    {t(`captcha.providers.${provider}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
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
              value={form.values.secret}
              onChange={(event) => form.set({ secret: event.target.value })}
              placeholder={saved.has_secret_key ? t("captcha.secretKeySet") : ""}
            />
          </Field>
          {!saved.enforcing && form.values.provider !== NO_CAPTCHA && (
            <p className="text-muted-foreground text-sm">{t("captcha.incomplete")}</p>
          )}
          <DialogFooter submitLabel={t("common:save")} pending={update.isPending} />
        </form>
      </DialogContent>
    </Dialog>
  );
};
