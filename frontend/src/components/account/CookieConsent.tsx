import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PrivacyLink } from "@/components/auth/LegalNotice";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useConsent } from "@/hooks/useConsent";
import { useServer } from "@/hooks/useServer";
import { captchaProvider } from "@/lib/captchaProviders";
import { type ConsentCategory, dismissReopenedConsent, recordConsent } from "@/lib/consent";
import { COOKIE_DOCS_URL } from "@/lib/links";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

/**
 * The cookie question, put once to somebody arriving.
 *
 * Refusing is a single click sitting beside accepting, at the same size:
 * there is no arrangement of this where agreeing is the quick way out.
 * Everything optional stays off until it is switched on here, so closing the
 * chooser, ignoring it, or never seeing it all land in the same place.
 *
 * What is strictly needed to run the app is stated rather than offered. It has
 * no switch because it has no alternative — the sign-in session, the theme,
 * what you had open — and a switch that cannot move would suggest otherwise.
 *
 * The optional switches are the ones the server says this deployment actually
 * uses. A deployment using none of them — the ordinary case for somebody
 * running this on their own server — is not shown switches for things it does
 * not do, and gets the statement with one way to close it.
 *
 * Off unless the deployment turned it on (``cookie_consent_enabled``), since
 * most deployments are a group's own server reached by people who were sent a
 * link. Mounted once at the root, like the step-up dialogs: a first arrival is
 * as likely to be an invite link or the sign-in page as the landing page.
 */
export const CookieConsent = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { isNativePlatform } = useServer();
  const { captcha, cookieCategories, cookieConsentEnabled, isLoading } = useAppConfig();
  const { unanswered, reopened, granted } = useConsent();

  // Somebody reopening this came to change something, so it opens on the
  // switches rather than making them ask for them again.
  const [choosing, setChoosing] = useState(false);
  const [draft, setDraft] = useState<readonly ConsentCategory[]>(granted);

  // Reopening starts from what is actually in force, not from whatever the
  // switches were left on the last time this was mounted.
  const [wasReopened, setWasReopened] = useState(reopened);
  if (reopened !== wasReopened) {
    setWasReopened(reopened);
    if (reopened) setDraft(granted);
  }

  // The installed app's disclosures are the store's, and there is no site to
  // have landed on.
  if (isNativePlatform || isLoading || !cookieConsentEnabled) {
    return null;
  }
  if (!unanswered && !reopened) {
    return null;
  }

  const spamCheck = captcha ? captchaProvider(captcha.provider) : undefined;
  const offered = cookieCategories;
  const nothingOptional = offered.length === 0;
  const showingSwitches = !nothingOptional && (choosing || reopened);

  const decide = (categories: readonly ConsentCategory[]) => {
    const { revoked } = recordConsent(categories);
    setChoosing(false);
    // Something already loaded cannot be taken off the page it is on, so the
    // page is built again without it.
    if (revoked.length > 0) {
      window.location.reload();
    }
  };

  const toggle = (category: ConsentCategory, on: boolean) =>
    setDraft((current) =>
      on ? [...current, category] : current.filter((held) => held !== category)
    );

  return (
    // The strip takes no pointer events, so the page underneath stays usable
    // either side of the card.
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center p-4"
      style={{ paddingBottom: "calc(1rem + var(--safe-area-inset-bottom))" }}
    >
      <section
        aria-label={t("legal:cookies.label")}
        className="pointer-events-auto flex w-full max-w-3xl flex-col gap-4 rounded-lg border bg-background/95 p-4 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-background/85"
      >
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-medium text-sm">{t("legal:cookies.title")}</p>
            <p className="text-muted-foreground text-sm">
              {t("legal:cookies.body", { appName: t("common:appName") })}{" "}
              {nothingOptional
                ? t("legal:cookies.nothingOptional")
                : t("legal:cookies.optionalIntro")}
            </p>
            {spamCheck ? (
              <p className="text-muted-foreground text-sm">
                {t("legal:cookies.spamCheck", { provider: spamCheck.name })}
              </p>
            ) : null}
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-sm">
              <a
                href={COOKIE_DOCS_URL}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline-offset-4 hover:underline"
              >
                {t("legal:cookies.readMore")}
              </a>
              {/* Only where the deployment has a policy of its own to read. */}
              <PrivacyLink />
            </p>
          </div>
          {/* Closing is only offered where there is already an answer to leave
              alone. With the question still open there is nothing to fall back
              on, and a close would have to stand for one answer or the other. */}
          {reopened ? (
            <Button
              variant="ghost"
              size="icon"
              onClick={dismissReopenedConsent}
              aria-label={t("common:close")}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          ) : null}
        </div>

        {showingSwitches ? (
          <div className="space-y-3 border-t pt-4">
            {/* Stated, not offered: there is no version of the app without it. */}
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-0.5">
                <p className="font-medium text-sm">
                  {t("legal:cookies.categories.necessary.name")}
                </p>
                <p className="text-muted-foreground text-sm">
                  {t("legal:cookies.categories.necessary.description")}
                </p>
              </div>
              <span className="shrink-0 text-muted-foreground text-xs">
                {t("legal:cookies.alwaysOn")}
              </span>
            </div>

            {offered.map((category) => (
              <div key={category} className="flex items-start justify-between gap-4">
                <div className="space-y-0.5">
                  <Label htmlFor={`consent-${category}`} className="font-medium text-sm">
                    {t(`legal:cookies.categories.${category}.name`)}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t(`legal:cookies.categories.${category}.description`)}
                  </p>
                </div>
                <Switch
                  id={`consent-${category}`}
                  checked={draft.includes(category)}
                  onCheckedChange={(checked) => toggle(category, Boolean(checked))}
                  className="shrink-0"
                />
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {/* With nothing optional in use there is no question, so there is
              one button and it agrees to nothing. */}
          {nothingOptional ? (
            <Button variant="outline" onClick={() => decide([])}>
              {t("legal:cookies.acknowledge")}
            </Button>
          ) : (
            <>
              {/* Refuse and accept are the same size and the same weight, side
                  by side, so neither is the path of least resistance. */}
              <Button variant="outline" onClick={() => decide([])} className="flex-1 sm:flex-none">
                {t("legal:cookies.rejectAll")}
              </Button>
              <Button
                variant="outline"
                onClick={() => decide(offered)}
                className="flex-1 sm:flex-none"
              >
                {t("legal:cookies.acceptAll")}
              </Button>
              {showingSwitches ? (
                <Button variant="ghost" onClick={() => decide(draft)}>
                  {t("legal:cookies.save")}
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => setChoosing(true)}>
                  {t("legal:cookies.choose")}
                </Button>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
};
