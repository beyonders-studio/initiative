import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useConsent } from "@/hooks/useConsent";
import { reopenConsent } from "@/lib/consent";
import { Button } from "@/ui/button";

/**
 * What this browser is currently allowing, and the way to change it.
 *
 * Here because a landing-page footer is no use to somebody already signed in
 * and three pages deep, and taking an answer back has to stay as easy as
 * giving one.
 *
 * Shown where ``usePrivacySections`` says there is something to change. It
 * reads this browser, which is what governs what loads here. The answer
 * also belongs to the account (see `useConsentSync`), so changing it here
 * reaches the other browsers this account signs in from.
 */
export const CookieChoicesSection = () => {
  const { t } = useTranslation(["settings", "legal"]);
  const { cookieCategories } = useAppConfig();
  const { unanswered, granted } = useConsent();

  const allowed = cookieCategories.filter((category) => granted.includes(category));

  return (
    <SettingsSection title={t("settings:privacy.cookies.title")}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="max-w-prose text-muted-foreground text-sm">
            {unanswered
              ? t("settings:privacy.cookies.unanswered")
              : allowed.length === 0
                ? t("settings:privacy.cookies.noneAllowed")
                : t("settings:privacy.cookies.allowed", {
                    categories: allowed
                      .map((category) => t(`legal:cookies.categories.${category}.name`))
                      .join(", "),
                  })}
          </p>
          <p className="max-w-prose text-muted-foreground text-xs">
            {t("settings:privacy.cookies.perBrowser")}
          </p>
        </div>
        <Button variant="outline" onClick={reopenConsent} className="shrink-0">
          {t("settings:privacy.cookies.change")}
        </Button>
      </div>
    </SettingsSection>
  );
};
