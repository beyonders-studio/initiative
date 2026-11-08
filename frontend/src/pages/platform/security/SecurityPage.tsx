import { useState } from "react";
import { useTranslation } from "react-i18next";

import { OnOffRuleDialog } from "@/components/settings/OnOffRuleDialog";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import {
  useCaptchaSettings,
  usePlatformAuthSettings,
  useUpdatePlatformAuthSettings,
} from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { listFormat } from "@/ui/lib/intl";

import { CaptchaDialog } from "./CaptchaDialog";
import { FactorMethodsDialog } from "./FactorMethodsDialog";
import { NotificationDeliverySection } from "./NotificationDeliverySection";
import { SecondFactorRequirementDialog } from "./SecondFactorRequirementDialog";
import { SessionLengthDialog } from "./SessionLengthDialog";

/** The rules a Sign-in rules row changes. */
type SignInRule = "second_factor" | "factor_methods" | "session" | "breached_check" | "captcha";

export const SecurityPage = () => {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const allowed = hasCapability(user, Capability.configManage);
  const settings = usePlatformAuthSettings({ enabled: allowed }).data;
  const captcha = useCaptchaSettings({ enabled: allowed }).data;
  const [changing, setChanging] = useState<SignInRule | null>(null);
  const closeDialog = (open: boolean) => {
    if (!open) setChanging(null);
  };
  const updateBreachedCheck = useUpdatePlatformAuthSettings(
    {
      onSuccess: (result) => {
        toast.success(
          result.breached_password_check_enabled
            ? t("auth.breachedPasswordCheck.enabledToast")
            : t("auth.breachedPasswordCheck.disabledToast")
        );
        setChanging(null);
      },
    },
    "settings:auth.breachedPasswordCheck.error"
  );

  if (!allowed) {
    return <p className="text-muted-foreground text-sm">{t("auth.platformOnly")}</p>;
  }

  const factors = settings?.methods.filter((entry) => entry.answers_factor) ?? [];
  const offered = factors
    .filter((entry) => entry.enabled)
    .map((entry) => t(`auth.methods.${entry.method}.label`));

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">{t("platformSecurity.description")}</p>

      {settings ? (
        <>
          <SettingsSection
            title={t("platformSecurity.signInRules.title")}
            description={t("platformSecurity.signInRules.description")}
          >
            {/* With nothing offered that could answer it there is nothing to
                ask people for, and the server refuses the write, so the row
                says what to do first instead of offering the change. */}
            <SettingsRow
              label={t("auth.secondFactorRequirement.title")}
              value={t(
                `auth.secondFactorRequirement.levels.${settings.second_factor_requirement}.label`
              )}
              description={
                settings.factor_methods_permitted
                  ? null
                  : t("auth.secondFactorRequirement.noMethod")
              }
              onChange={
                settings.factor_methods_permitted ? () => setChanging("second_factor") : undefined
              }
            />
            {factors.length > 0 && (
              <SettingsRow
                label={t("auth.factorMethods.title")}
                value={
                  offered.length > 0
                    ? listFormat(i18n.resolvedLanguage ?? i18n.language).format(offered)
                    : t("auth.factorMethods.none")
                }
                onChange={() => setChanging("factor_methods")}
              />
            )}
            <SettingsRow
              label={t("auth.sessionLifetime.title")}
              value={
                settings.session_max_hours == null
                  ? t("auth.sessionLifetime.placeholder")
                  : t("settingsSection.hours", { count: settings.session_max_hours })
              }
              description={
                settings.session_idle_minutes == null
                  ? t("auth.sessionLifetime.idleDefault")
                  : t("auth.sessionLifetime.idleDetail", { count: settings.session_idle_minutes })
              }
              onChange={() => setChanging("session")}
            />
            <SettingsRow
              label={t("auth.breachedPasswordCheck.title")}
              value={
                settings.breached_password_check_enabled
                  ? t("settingsSection.on")
                  : t("settingsSection.off")
              }
              onChange={() => setChanging("breached_check")}
            />
            {captcha && (
              <SettingsRow
                label={t("captcha.title")}
                value={
                  captcha.provider
                    ? t(`captcha.providers.${captcha.provider}`)
                    : t("settingsSection.off")
                }
                description={
                  captcha.provider && !captcha.enforcing ? t("captcha.missingKeys") : null
                }
                onChange={() => setChanging("captcha")}
              />
            )}
          </SettingsSection>

          <SecondFactorRequirementDialog
            settings={settings}
            open={changing === "second_factor"}
            onOpenChange={closeDialog}
          />
          <FactorMethodsDialog
            settings={settings}
            open={changing === "factor_methods"}
            onOpenChange={closeDialog}
          />
          <SessionLengthDialog
            settings={settings}
            open={changing === "session"}
            onOpenChange={closeDialog}
          />
          <OnOffRuleDialog
            id="breached-password-check"
            title={t("auth.breachedPasswordCheck.title")}
            description={t("auth.breachedPasswordCheck.description")}
            onLabel={t("auth.breachedPasswordCheck.onLabel")}
            offLabel={t("auth.breachedPasswordCheck.offLabel")}
            saved={settings.breached_password_check_enabled}
            pending={updateBreachedCheck.isPending}
            onSave={(on) => updateBreachedCheck.mutate({ breached_password_check_enabled: on })}
            open={changing === "breached_check"}
            onOpenChange={closeDialog}
          />
          {captcha && (
            <CaptchaDialog
              saved={captcha}
              open={changing === "captcha"}
              onOpenChange={closeDialog}
            />
          )}
        </>
      ) : null}

      <NotificationDeliverySection />
    </div>
  );
};
