/**
 * Connect an identity provider, one question at a time.
 *
 * The old form asked for eight fields at once and told you nothing until
 * somebody tried to sign in. Four of those fields are only knowable at the
 * other end, one of them is a URL people get subtly wrong, and one — the
 * callback — has to go the other way, from here into the provider. A single
 * form is the wrong shape for that: it is a conversation between two screens.
 *
 * So: which provider, then its address (checked before we go on), then the
 * credentials with the callback to take back with you, then the options that
 * have sensible answers already.
 *
 *   1. Which one       — a grid, because the names are the choice
 *   2. Its address     — built from the preset's blanks, then verified
 *   3. Credentials     — the callback to copy, then the two values it returns
 *   4. How it behaves  — scopes and groups filled in from what it told us
 *
 * Editing does not come through here. Somebody changing one field should not
 * walk four screens, so the flat form stays for that — with the same Verify
 * and the same callback to copy.
 */

import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AuthProviderCreate,
  AuthProviderProbeResult,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { useWizard } from "@/hooks/useWizard";
import {
  buildIssuer,
  DEFAULT_SCOPES,
  GROUPS_CLAIM_SUGGESTIONS,
  isCustomPreset,
  issuerIsComplete,
  PROVIDER_PRESETS,
  type ProviderPreset,
  presetFor,
  suggestScopes,
} from "@/lib/authProviderPresets";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { isValidProviderSlug } from "@/lib/providerSlug";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { CopyButton } from "@/ui/copy-button";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";
import { WizardDialog } from "@/ui/wizard-dialog";

type Step = "choose" | "address" | "credentials" | "options";

const STEP_ORDER: Step[] = ["choose", "address", "credentials", "options"];

/** The mutation surface, satisfied structurally by either registry's hooks so
 *  the operator and community wrappers plug in without sharing a hook signature. */
export interface WizardMutation<TVariables, TResult = unknown> {
  mutate: (
    variables: TVariables,
    options?: { onSuccess?: (data: TResult) => void; onError?: (error: unknown) => void }
  ) => void;
  isPending: boolean;
}

export interface ConnectProviderWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  createProvider: WizardMutation<AuthProviderCreate>;
  discoverIssuer: WizardMutation<{ issuer: string }, AuthProviderProbeResult>;
}

export const ConnectProviderWizard = ({
  open,
  onOpenChange,
  createProvider,
  discoverIssuer,
}: ConnectProviderWizardProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const { step, go, back, canGoBack, reset } = useWizard<Step>("choose");

  const [preset, setPreset] = useState<ProviderPreset>(presetFor("custom"));
  const [blanks, setBlanks] = useState<Record<string, string>>({});
  const [typedIssuer, setTypedIssuer] = useState("");
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState(DEFAULT_SCOPES.join(" "));
  const [groupsClaim, setGroupsClaim] = useState("");
  const [allowJit, setAllowJit] = useState(true);
  const [enabled, setEnabled] = useState(true);
  /** The look-up, and the address it was asked about. Kept together so an
   *  answer that arrives after the address moved on is not mistaken for an
   *  answer about the address now showing. */
  const [probe, setProbe] = useState<{
    forIssuer: string;
    result: AuthProviderProbeResult;
  } | null>(null);
  const [slugError, setSlugError] = useState(false);

  const issuer = isCustomPreset(preset) ? typedIssuer.trim() : buildIssuer(preset, blanks);
  const addressReady = isCustomPreset(preset)
    ? /^https:\/\/.+/.test(issuer)
    : issuerIsComplete(preset, blanks);
  // The answer only counts while it is about the address on screen, so
  // editing it — or editing it mid-flight — puts the tick away rather than
  // leaving it vouching for somewhere else.
  const shown = probe?.forIssuer === issuer ? probe.result : null;
  const verified = shown?.ok === true && shown.issuer !== null;
  const callbackUrl = (shown?.callback_url_template ?? "").replace("{slug}", slug || "{slug}");

  const closeWizard = () => {
    onOpenChange(false);
    reset();
    setPreset(presetFor("custom"));
    setBlanks({});
    setTypedIssuer("");
    setSlug("");
    setDisplayName("");
    setClientId("");
    setClientSecret("");
    setScopes(DEFAULT_SCOPES.join(" "));
    setGroupsClaim("");
    setAllowJit(true);
    setEnabled(true);
    setProbe(null);
    setSlugError(false);
  };

  const choosePreset = (chosen: ProviderPreset) => {
    setPreset(chosen);
    setBlanks({});
    setTypedIssuer("");
    setProbe(null);
    setSlug(chosen.slug);
    setDisplayName(chosen.key === "custom" ? "" : chosen.name);
    setSlugError(false);
    go("address");
  };

  const verify = () => {
    const asked = issuer;
    discoverIssuer.mutate(
      { issuer: asked },
      {
        onSuccess: (result) => {
          // Recorded against the address asked about, not the address now.
          setProbe({ forIssuer: asked, result });
          // What it says it offers is a better starting point than our guess.
          if (result.ok) setScopes(suggestScopes(result.scopes_supported));
        },
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:authProviders.verifyError")),
      }
    );
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isValidProviderSlug(slug)) {
      setSlugError(true);
      return;
    }
    createProvider.mutate(
      {
        slug,
        display_name: displayName,
        // The address that answered, which may be the typed one trimmed of a
        // pasted `.well-known` suffix. `shown` is only set while the answer is
        // about the address on screen, so this can never save a stale one.
        issuer: shown?.issuer ?? issuer,
        client_id: clientId,
        client_secret: clientSecret || null,
        scopes: scopes || null,
        role_claim_path: groupsClaim.trim() || null,
        allow_jit: allowJit,
        // Ticked for the products that document the claim, and the operator's
        // to change on the provider's own page either way: how an IdP is
        // configured is theirs, not something this list can know.
        asserts_second_factor: preset.assertsSecondFactor ?? false,
        enabled,
        // The preset key doubles as the mark, `custom` included: a
        // hand-configured provider gets the standard’s own mark.
        icon: preset.key,
      },
      {
        onSuccess: () => {
          toast.success(t("authProviders.created"));
          closeWizard();
        },
        onError: (error) => toast.error(getErrorMessage(error, "settings:authProviders.saveError")),
      }
    );
  };

  const stepDescription: Record<Step, string> = {
    choose: t("authProviders.wizard.choosePrompt"),
    address: t("authProviders.wizard.addressPrompt", { name: preset.name }),
    credentials: t("authProviders.wizard.credentialsPrompt", { name: preset.name }),
    options: t("authProviders.wizard.optionsPrompt"),
  };

  return (
    <WizardDialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : closeWizard())}
      className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
      title={t("authProviders.wizard.title")}
      description={stepDescription[step]}
      progress={{ current: STEP_ORDER.indexOf(step) + 1, total: STEP_ORDER.length }}
      onBack={canGoBack ? back : undefined}
      backLabel={t("common:back")}
    >
      {step === "choose" && (
        <div className="grid grid-cols-2 gap-2">
          {PROVIDER_PRESETS.map((option) => (
            <button
              key={option.key}
              type="button"
              className="flex items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent"
              onClick={() => choosePreset(option)}
            >
              {/* `custom` has a mark of its own — the standard's. */}
              <ProviderMark icon={option.key} />
              <span className="min-w-0 truncate font-medium text-sm">{option.name}</span>
            </button>
          ))}
        </div>
      )}

      {step === "address" && (
        <div className="space-y-4">
          {preset.hintKey ? (
            <p className="text-muted-foreground text-sm">
              {t(`authProviders.presetHints.${preset.hintKey}`)}
            </p>
          ) : null}

          {/* The blanks, each asked for on its own. Nobody should be editing
              the middle of a URL to supply a realm. */}
          {preset.blanks.map((blank) => (
            <div key={blank.name} className="space-y-2">
              <Label htmlFor={`provider-blank-${blank.name}`}>
                {t(`authProviders.blanks.${blank.labelKey}`)}
              </Label>
              <Input
                id={`provider-blank-${blank.name}`}
                value={blanks[blank.name] ?? ""}
                placeholder={blank.example}
                onChange={(event) => {
                  setProbe(null);
                  setBlanks((prev) => ({ ...prev, [blank.name]: event.target.value }));
                }}
              />
            </div>
          ))}

          {isCustomPreset(preset) ? (
            <div className="space-y-2">
              <Label htmlFor="provider-issuer">{t("authProviders.issuerLabel")}</Label>
              <Input
                id="provider-issuer"
                type="url"
                value={typedIssuer}
                placeholder={t("authProviders.issuerPlaceholder")}
                onChange={(event) => {
                  setProbe(null);
                  setTypedIssuer(event.target.value);
                }}
              />
            </div>
          ) : (
            <div className="space-y-1">
              <Label>{t("authProviders.issuerLabel")}</Label>
              <code className="block truncate rounded bg-muted px-2 py-1.5 text-xs">
                {issuer || preset.template}
              </code>
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={verify}
              disabled={!addressReady || discoverIssuer.isPending}
            >
              {discoverIssuer.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("authProviders.verifying")}
                </>
              ) : (
                t("authProviders.verify")
              )}
            </Button>
          </div>

          {shown ? <ProbeReport probe={shown} /> : null}

          <Button
            className="w-full"
            disabled={!verified}
            onClick={() => go("credentials")}
            type="button"
          >
            {t("authProviders.wizard.nextCredentials")}
          </Button>
        </div>
      )}

      {step === "credentials" && (
        <div className="space-y-4">
          {/* First, because it goes the other way: this is the one value that
              travels from here into the provider. */}
          <div className="space-y-2 rounded-md border bg-muted/40 p-3">
            <Label>{t("authProviders.wizard.registerCallback")}</Label>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1.5 text-xs">
                {callbackUrl}
              </code>
              <CopyButton value={callbackUrl} copiedMessage={t("authProviders.callbackCopied")} />
            </div>
            <p className="text-muted-foreground text-xs">
              {t("authProviders.wizard.callbackHelp")}
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="provider-client-id">{t("authProviders.clientIdLabel")}</Label>
            <Input
              id="provider-client-id"
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="provider-client-secret">{t("authProviders.clientSecretLabel")}</Label>
            <Input
              id="provider-client-secret"
              type="password"
              value={clientSecret}
              placeholder={t("authProviders.secretPlaceholder")}
              onChange={(event) => setClientSecret(event.target.value)}
            />
          </div>

          <Button
            className="w-full"
            type="button"
            disabled={!clientId.trim()}
            onClick={() => go("options")}
          >
            {t("authProviders.wizard.nextOptions")}
          </Button>
        </div>
      )}

      {step === "options" && (
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-2">
            <Label htmlFor="provider-slug">{t("authProviders.slugLabel")}</Label>
            <Input
              id="provider-slug"
              value={slug}
              maxLength={64}
              required
              onChange={(event) => {
                setSlugError(false);
                setSlug(event.target.value);
              }}
            />
            {slugError ? (
              <p className="text-destructive text-xs">{t("authProviders.slugInvalid")}</p>
            ) : (
              <p className="text-muted-foreground text-xs">{t("authProviders.slugHelp")}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="provider-display-name">{t("authProviders.displayNameLabel")}</Label>
            <Input
              id="provider-display-name"
              value={displayName}
              required
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="provider-scopes">{t("authProviders.scopesLabel")}</Label>
            <Input
              id="provider-scopes"
              value={scopes}
              onChange={(event) => setScopes(event.target.value)}
            />
            {shown && shown.scopes_supported.length > 0 ? (
              <p className="text-muted-foreground text-xs">
                {t("authProviders.scopesFromProvider")}
              </p>
            ) : null}
          </div>

          <div className="space-y-1">
            <Label>{t("authProviders.claimPathLabel")}</Label>
            <Combobox
              items={[
                ...new Set([...(shown?.claims_supported ?? []), ...GROUPS_CLAIM_SUGGESTIONS]),
              ].map((claim) => ({ value: claim, label: claim }))}
              value={groupsClaim}
              selectedLabel={groupsClaim}
              onValueChange={setGroupsClaim}
              placeholder={t("authProviders.claimPathPlaceholder")}
              searchPlaceholder={t("authProviders.claimPathSearch")}
              emptyMessage={t("authProviders.claimPathEmpty")}
              typedLabel={(value) => t("authProviders.claimPathUseTyped", { value })}
              aria-label={t("authProviders.claimPathLabel")}
            />
            <p className="text-muted-foreground text-xs">{t("authProviders.claimPathHelp")}</p>
          </div>

          <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
            <div>
              <Label htmlFor="provider-allow-jit" className="font-medium">
                {t("authProviders.allowJitLabel")}
              </Label>
              <p className="text-muted-foreground text-xs">{t("authProviders.allowJitHelp")}</p>
            </div>
            <Switch
              id="provider-allow-jit"
              checked={allowJit}
              onCheckedChange={(checked) => setAllowJit(Boolean(checked))}
            />
          </div>

          <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
            <Label htmlFor="provider-enabled" className="font-medium">
              {t("authProviders.enabledLabel")}
            </Label>
            <Switch
              id="provider-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(Boolean(checked))}
            />
          </div>

          <Button className="w-full" type="submit" disabled={createProvider.isPending}>
            {createProvider.isPending
              ? t("authProviders.saving")
              : t("authProviders.wizard.connect")}
          </Button>
        </form>
      )}
    </WizardDialog>
  );
};

/** What the look-up found, in the two shapes it comes in. */
export const ProbeReport = ({ probe }: { probe: AuthProviderProbeResult }) => {
  const { t } = useTranslation("settings");

  if (!probe.ok) {
    return (
      <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium text-sm">{t("authProviders.probe.failed")}</p>
          <p className="text-muted-foreground text-xs">
            {messageForCode(probe.error_code, "settings:authProviders.probe.failed")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 rounded-md border border-primary/40 bg-primary/5 p-3">
      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <div className="min-w-0 space-y-1">
        <p className="font-medium text-sm">{t("authProviders.probe.reachable")}</p>
        <dl className="space-y-0.5 text-muted-foreground text-xs">
          <ProbeRow
            label={t("authProviders.probe.authorize")}
            value={probe.authorization_endpoint}
          />
          <ProbeRow label={t("authProviders.probe.token")} value={probe.token_endpoint} />
          <ProbeRow label={t("authProviders.probe.keys")} value={probe.jwks_uri} />
          {probe.signing_algs.length > 0 ? (
            <ProbeRow
              label={t("authProviders.probe.signing")}
              value={probe.signing_algs.join(", ")}
            />
          ) : null}
        </dl>
      </div>
    </div>
  );
};

const ProbeRow = ({ label, value }: { label: string; value: string | null }) =>
  value ? (
    <div className="flex gap-2">
      <dt className="shrink-0">{label}</dt>
      <dd className="min-w-0 truncate font-mono">{value}</dd>
    </div>
  ) : null;
