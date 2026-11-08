/**
 * Platform → Security.
 *
 * What the deployment asks of everybody's sign-in, rather than how anybody
 * signs in — that is Authentication, next door. Each sign-in rule is a row
 * that states its current value and changes in a dialog: who has to hold a
 * second factor and which ones are offered, how long a session may last,
 * whether a new password is checked against known breaches, and the captcha
 * asked of somebody new. Then what a notification may leave the app carrying,
 * whose switches save as they are flipped.
 *
 * Written here and enforced server-side, so what this page does is offer each
 * choice and state what it costs, never decide it.
 */

import { isAxiosError } from "axios";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import type {
  CaptchaSettingsResponse,
  CaptchaSettingsUpdate,
  LoginMethod,
  PlatformAuthSettingsResponse,
  SecondFactorRequirement,
} from "@/api/generated/initiativeAPI.schemas";
import { NotificationDeliverySection } from "@/components/platform/NotificationDeliverySection";
import { OnOffRuleDialog } from "@/components/settings/OnOffRuleDialog";
import { SettingsRow, SettingsSection, WhenYouSave } from "@/components/settings/SettingsSection";
import { useAuth } from "@/hooks/useAuth";
import { useServerForm } from "@/hooks/useServerForm";
import {
  useAuthProviders,
  useCaptchaSettings,
  usePlatformAuthSettings,
  useUpdateAuthProvider,
  useUpdateCaptchaSettings,
  useUpdatePlatformAuthSettings,
} from "@/hooks/useSettings";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Capability, hasCapability } from "@/lib/permissions";
import { readOptionalWholeNumber } from "@/lib/text";
import { Alert, AlertDescription } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
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
import { Label } from "@/ui/label";
import { listFormat } from "@/ui/lib/intl";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/** The rules a Sign-in rules row changes. */
type SignInRule = "second_factor" | "factor_methods" | "session" | "breached_check" | "captcha";

/** Who has to hold a second factor, in the order the answers widen. */
const LEVELS = ["nobody", "platform_roles", "everyone"] as const;

const CAPTCHA_PROVIDERS = ["hcaptcha", "turnstile", "recaptcha"] as const;
type CaptchaProvider = (typeof CAPTCHA_PROVIDERS)[number];
const NO_CAPTCHA = "off";

const isCaptchaProvider = (value: string): value is CaptchaProvider =>
  (CAPTCHA_PROVIDERS as readonly string[]).includes(value);

/** A second factor this page turns on and off. A passkey is also a way in,
 *  so it is set under Ways in and only shown here. */
const setHere = (entry: { answers_factor: boolean; primary: boolean }) =>
  entry.answers_factor && !entry.primary;

interface RuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Who has to hold a second factor. What satisfies it is the account holding a
 * factor, or a session that presented one, which is what an identity
 * provider's own second factor looks like from here.
 */
const SecondFactorRequirementDialog = ({
  settings,
  open,
  onOpenChange,
}: RuleDialogProps & { settings: PlatformAuthSettingsResponse }) => {
  const { t } = useTranslation(["settings", "common"]);
  const saved = settings.second_factor_requirement;
  const form = useServerForm(
    saved,
    (loaded) => ({ choice: loaded ?? ("nobody" as SecondFactorRequirement) }),
    open
  );
  const { choice } = form.values;
  /** Set when the server refuses because this account does not meet the rule
   *  itself. Answered where they stand, by the dialog every refusal opens. */
  const [unmet, setUnmet] = useState(false);

  const close = () => {
    onOpenChange(false);
    setUnmet(false);
  };

  const update = useUpdatePlatformAuthSettings({
    onSuccess: () => {
      toast.success(t("auth.secondFactorRequirement.saved"));
      close();
    },
    onError: (err) => {
      if (isAxiosError(err) && getErrorCode(err) === "AUTH_RULE_SELF_UNSATISFIED") {
        setUnmet(true);
        return;
      }
      setUnmet(false);
      toast.error(getErrorMessage(err, "settings:auth.secondFactorRequirement.error"));
    },
  });

  // Only a wider answer asks anything of anybody; a narrower one just saves.
  const widens = LEVELS.indexOf(choice) > LEVELS.indexOf(saved);
  const withoutFactor = settings.accounts_without_factor;
  /** How many accounts the chosen answer would ask to set one up. */
  const wouldAsk =
    choice === "everyone"
      ? withoutFactor.everyone
      : choice === "platform_roles"
        ? withoutFactor.platform_roles
        : 0;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("auth.secondFactorRequirement.title")}</DialogTitle>
          <DialogDescription>{t("auth.secondFactorRequirement.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RadioGroup
            value={choice}
            onValueChange={(value) => {
              form.set({ choice: value as SecondFactorRequirement });
              setUnmet(false);
            }}
            className="gap-3"
          >
            {LEVELS.map((level) => (
              <div key={level} className="flex items-start gap-3 rounded-md border px-4 py-3">
                <RadioGroupItem id={`second-factor-${level}`} value={level} className="mt-1" />
                <div className="space-y-1">
                  <Label htmlFor={`second-factor-${level}`} className="font-medium text-base">
                    {t(`auth.secondFactorRequirement.levels.${level}.label`)}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t(`auth.secondFactorRequirement.levels.${level}.help`)}
                  </p>
                </div>
              </div>
            ))}
          </RadioGroup>

          <ProvidersThatCount />

          <WhenYouSave
            lines={
              widens
                ? [
                    wouldAsk > 0 && t("auth.secondFactorRequirement.wouldAsk", { count: wouldAsk }),
                    t("auth.secondFactorRequirement.derivedCredentials"),
                  ]
                : []
            }
          />

          {unmet && (
            <Alert>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                <span>{t("auth.secondFactorRequirement.unmet")}</span>
                <Button
                  size="sm"
                  onClick={() =>
                    window.dispatchEvent(
                      new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
                        detail: { communityId: null, kind: "totp" },
                      })
                    )
                  }
                >
                  {t("auth.secondFactorRequirement.present")}
                </Button>
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={choice === saved}
          onSubmit={() => update.mutate({ second_factor_requirement: choice })}
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * Which providers' own account of a sign-in answers the second-factor rule.
 *
 * The same ``asserts_second_factor`` the registry holds, shown here because
 * this is where somebody decides who must hold a factor and therefore wants to
 * know who already does. Ticking either place writes the one answer, at once.
 */
const ProvidersThatCount = () => {
  const { t } = useTranslation("settings");
  const providersQuery = useAuthProviders();
  const updateProvider = useUpdateAuthProvider();
  const providers = providersQuery.data ?? [];

  if (providersQuery.isLoading || providers.length === 0) return null;

  return (
    <div className="space-y-3 rounded-md border px-4 py-3">
      <div className="space-y-1">
        <p className="font-medium text-sm">{t("auth.secondFactorRequirement.providers.title")}</p>
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.providers.help")}
        </p>
      </div>
      <ul className="space-y-2">
        {providers.map((provider) => (
          <li key={provider.id} className="flex items-center gap-3">
            <Checkbox
              id={`provider-counts-${provider.id}`}
              checked={provider.asserts_second_factor ?? false}
              disabled={updateProvider.isPending}
              onCheckedChange={(checked) =>
                updateProvider.mutate(
                  {
                    providerId: provider.id,
                    data: { asserts_second_factor: Boolean(checked) },
                  },
                  {
                    onError: (err: unknown) =>
                      toast.error(getErrorMessage(err, "settings:authProviders.saveError")),
                  }
                )
              }
            />
            <Label htmlFor={`provider-counts-${provider.id}`} className="font-normal">
              {provider.display_name}
            </Label>
          </li>
        ))}
      </ul>
    </div>
  );
};

/**
 * Which second factors this server offers. Two things can answer being asked
 * for one, and the server says which (`answers_factor`) rather than this
 * keeping a list. Withdrawing one strands nobody, because it was never
 * anybody's only way in; leaving a standing requirement with nothing to
 * answer it is refused by the server with its own message.
 */
const FactorMethodsDialog = ({
  settings,
  open,
  onOpenChange,
}: RuleDialogProps & { settings: PlatformAuthSettingsResponse }) => {
  const { t } = useTranslation(["settings", "common"]);
  const { methods } = settings;
  const form = useServerForm(
    methods,
    (loaded) => ({
      on: (loaded ?? []).filter((entry) => setHere(entry) && entry.enabled).map((m) => m.method),
    }),
    open
  );
  const update = useUpdatePlatformAuthSettings({
    onSuccess: () => {
      toast.success(t("auth.factorMethods.saved"));
      onOpenChange(false);
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.factorMethods.saveError")),
  });

  const choose = (method: LoginMethod, checked: boolean) =>
    form.set((previous) => ({
      on: checked ? [...previous.on, method] : previous.on.filter((m) => m !== method),
    }));
  const changed = methods.some(
    (entry) => setHere(entry) && entry.enabled !== form.values.on.includes(entry.method)
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("auth.factorMethods.title")}</DialogTitle>
          <DialogDescription>{t("auth.factorMethods.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {methods
            .filter((entry) => entry.answers_factor)
            .map((entry) =>
              setHere(entry) ? (
                <SettingsRow
                  key={entry.method}
                  htmlFor={`factor-method-${entry.method}`}
                  label={t(`auth.methods.${entry.method}.label`)}
                  description={t(`auth.methods.${entry.method}.help`)}
                >
                  <Checkbox
                    id={`factor-method-${entry.method}`}
                    checked={form.values.on.includes(entry.method)}
                    onCheckedChange={(checked) => choose(entry.method, Boolean(checked))}
                  />
                </SettingsRow>
              ) : (
                <SettingsRow
                  key={entry.method}
                  label={t(`auth.methods.${entry.method}.label`)}
                  value={entry.enabled ? t("settingsSection.on") : t("settingsSection.off")}
                  action={
                    <Badge variant="secondary">{t("auth.factorMethods.setUnderWaysIn")}</Badge>
                  }
                />
              )
            )}
        </div>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={!changed}
          onSubmit={() =>
            update.mutate({
              methods: [
                ...methods
                  .filter((entry) => entry.enabled && !setHere(entry))
                  .map((entry) => entry.method),
                ...form.values.on,
              ],
            })
          }
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * How long somebody may stay signed in before signing in again, and how long
 * a session may sit untouched. Saved together, because they are two halves of
 * one answer and the server takes them in one write. Blank asks for no limit,
 * which is where a self-hosted deployment starts.
 */
const SessionLengthDialog = ({
  settings,
  open,
  onOpenChange,
}: RuleDialogProps & { settings: PlatformAuthSettingsResponse }) => {
  const { t } = useTranslation(["settings", "common"]);
  const form = useServerForm(
    settings,
    (loaded) => ({
      hours: loaded?.session_max_hours == null ? "" : String(loaded.session_max_hours),
      idle: loaded?.session_idle_minutes == null ? "" : String(loaded.session_idle_minutes),
    }),
    open
  );
  const update = useUpdatePlatformAuthSettings({
    onSuccess: () => {
      toast.success(t("auth.sessionLifetime.saved"));
      onOpenChange(false);
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.sessionLifetime.error")),
  });

  const maxHours = readOptionalWholeNumber(form.values.hours, 1);
  const idleLimit = readOptionalWholeNumber(form.values.idle, 1);
  const changed =
    maxHours.value !== settings.session_max_hours ||
    idleLimit.value !== settings.session_idle_minutes;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("auth.sessionLifetime.title")}</DialogTitle>
          <DialogDescription>{t("auth.sessionLifetime.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label={t("auth.sessionLifetime.label")} hint={t("auth.sessionLifetime.hint")}>
            <Input
              type="number"
              min={1}
              className="w-40"
              value={form.values.hours}
              onChange={(event) => form.set({ hours: event.target.value })}
              placeholder={t("auth.sessionLifetime.placeholder")}
            />
          </Field>
          <Field
            label={t("auth.sessionLifetime.idleLabel")}
            hint={t("auth.sessionLifetime.idleHint")}
          >
            <Input
              type="number"
              min={1}
              className="w-40"
              value={form.values.idle}
              onChange={(event) => form.set({ idle: event.target.value })}
              placeholder={t("auth.sessionLifetime.idlePlaceholder")}
            />
          </Field>
        </div>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={!maxHours.valid || !idleLimit.valid || !changed}
          onSubmit={() =>
            update.mutate({
              session_max_hours: maxHours.value,
              session_idle_minutes: idleLimit.value,
            })
          }
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * The captcha asked of anybody signing up, or asking for an emailed sign-in
 * code. Three values, and it is on only when all three are there. The secret
 * is write-only: the page is told whether one is stored, never what it is, so
 * an empty field keeps it.
 */
const CaptchaDialog = ({
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
    onError: (err) => toast.error(getErrorMessage(err, "settings:captcha.error")),
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

export const SettingsPlatformSecurityPage = () => {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const allowed = hasCapability(user, Capability.configManage);
  const settings = usePlatformAuthSettings({ enabled: allowed }).data;
  const captcha = useCaptchaSettings({ enabled: allowed }).data;
  const [changing, setChanging] = useState<SignInRule | null>(null);
  const closeDialog = (open: boolean) => {
    if (!open) setChanging(null);
  };
  const updateBreachedCheck = useUpdatePlatformAuthSettings({
    onSuccess: (result) => {
      toast.success(
        result.breached_password_check_enabled
          ? t("auth.breachedPasswordCheck.enabledToast")
          : t("auth.breachedPasswordCheck.disabledToast")
      );
      setChanging(null);
    },
    onError: (err) =>
      toast.error(getErrorMessage(err, "settings:auth.breachedPasswordCheck.error")),
  });

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
