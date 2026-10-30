import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AUTH_FACTOR_REQUIRED_EVENT,
  type CommunityFactorKind,
  type FactorChallengeDetail,
} from "@/api/client";
import type {
  CommunityAuthPolicyRead,
  CommunityAuthPolicyUpdate,
  CommunityAuthSettingsRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CommunityAuthProvidersSection } from "@/components/auth/CommunityAuthProvidersSection";
import { CommunityClaimRulesSection } from "@/components/auth/CommunityClaimRulesSection";
import { CommunityEngagementRankingSection } from "@/components/auth/CommunityEngagementRankingSection";
import { CommunityNotificationPolicySection } from "@/components/auth/CommunityNotificationPolicySection";
import { ConnectSignInWizard } from "@/components/auth/ConnectSignInWizard";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useCommunityAuthSettings,
  useCommunityLoginProviders,
  useCommunityProviderConnections,
  useUpdateCommunityAuthSettings,
} from "@/hooks/useCommunityAuthPolicy";
import { useServer } from "@/hooks/useServer";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { providerSignInHref } from "@/lib/returnPath";
import { readOptionalWholeNumber } from "@/lib/text";

/**
 * Community sign-in configuration (Settings → Security), in two halves.
 *
 * "Who gets in" is the community's own identity provider registry, what the
 * claims arriving on it mean, and the sign-in requirement set against them —
 * sessions reach this community only after signing in through one specific
 * provider; `open` (the default) admits any signed-in session. "On what
 * terms" is what a session is allowed once it is here: how long it lasts and
 * whether a personal API key may be used against the community.
 */
/** The select's value for "any of ours" — a requirement that names no single
 * provider. Not a number, so it can never collide with a provider id. */
const ANY_PROVIDER = "any";

/**
 * What this admin's own session is missing, when saving a requirement is
 * refused because it does not meet the requirement itself. The server names
 * it; a provider is answered by signing in again, a factor of the account's
 * own by presenting it here.
 */
type Unmet = { kind: "provider"; slug: string } | { kind: CommunityFactorKind };

/** The two lines each factor needs: what to do, and the button that does it. */
const FACTOR_COPY = {
  totp: {
    line: "communityAuth.policy.unmetFactor",
    button: "communityAuth.policy.presentFactor",
  },
  passkey: {
    line: "communityAuth.policy.unmetPasskey",
    button: "communityAuth.policy.presentPasskey",
  },
} as const;

/** The method the server named on a refusal. Axios lower-cases header keys. */
const unmetMethod = (error: unknown): string | null => {
  const named = (error as { response?: { headers?: Record<string, unknown> } }).response?.headers?.[
    "x-auth-policy-unmet"
  ];
  return typeof named === "string" ? named : null;
};

/**
 * The state behind a switch that saves as it is flipped rather than waiting
 * for a button. The draft is what the switch shows until the saved answer
 * comes back; a failed save drops it and keeps a message.
 */
const useFlipToSave = (saved: boolean, communityId: number) => {
  const [state, setState] = useState<{
    communityId: number;
    draft: boolean | null;
    error: string | null;
  }>({ communityId, draft: null, error: null });
  const current =
    state.communityId === communityId ? state : { communityId, draft: null, error: null };
  return {
    value: current.draft ?? saved,
    error: current.error,
    begin: (next: boolean) => {
      setState({ communityId, draft: next, error: null });
    },
    settle: () => {
      setState((previous) =>
        previous.communityId === communityId ? { communityId, draft: null, error: null } : previous
      );
    },
    fail: (message: string) => {
      setState((previous) =>
        previous.communityId === communityId
          ? { communityId, draft: null, error: message }
          : previous
      );
    },
  };
};

/**
 * One sign-in requirement: the members' or, with `guest`, the guests'. The two
 * are set the same way; only the members' is asked of whoever saves it.
 */
const SignInRequirementCard = ({
  communityId,
  savedPolicy,
  eligibleProviders,
  mayConfigureProviders,
  guest = false,
}: {
  communityId: number;
  savedPolicy: CommunityAuthPolicyRead | undefined;
  eligibleProviders: { id: number; slug: string; display_name: string }[];
  mayConfigureProviders: boolean;
  guest?: boolean;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const copy = guest ? "communityAuth.guestPolicy" : "communityAuth.policy";
  const idPrefix = guest ? "guest-auth" : "community-auth";

  // Chosen here, saved by the button below — a refetch in between must not
  // undo the choice.
  const form = useServerForm(
    savedPolicy,
    (loaded) => ({
      policy: loaded?.policy ?? ("open" as "open" | "required"),
      providerId: loaded?.provider_id ?? null,
      // A rule that names no provider and asks for the community's own
      // single sign-on is the "any of ours" choice below.
      anyProvider: loaded?.provider_id == null && (loaded?.require_methods ?? []).includes("sso"),
      // Orthogonal to the provider choice: a community may ask for its own
      // sign-in, for a second factor, for a passkey, or for any combination.
      requirePasskey: (loaded?.require_methods ?? []).includes("passkey"),
    }),
    communityId
  );
  const { policy, providerId, anyProvider, requirePasskey } = form.values;
  const setPolicy = (next: "open" | "required") => form.set({ policy: next });
  const [error, setError] = useState<string | null>(null);
  const [unmet, setUnmet] = useState<Unmet | null>(null);

  // One mutation per control, so each keeps its own pending state and its own
  // callbacks when two are changed in quick succession.
  const updatePolicy = useUpdateCommunityAuthSettings(communityId);

  const selectedProvider = eligibleProviders.find((entry) => entry.id === providerId);
  const savedAnyProvider =
    savedPolicy != null &&
    savedPolicy.provider_id == null &&
    (savedPolicy.require_methods ?? []).includes("sso");
  const savedRequirePasskey =
    savedPolicy != null && (savedPolicy.require_methods ?? []).includes("passkey");
  const isDirty =
    savedPolicy != null &&
    (policy !== savedPolicy.policy ||
      (policy === "required" &&
        (anyProvider !== savedAnyProvider ||
          requirePasskey !== savedRequirePasskey ||
          (!anyProvider && providerId !== (savedPolicy.provider_id ?? null)))));
  // A rule has to ask for something. Any one of the four will do.
  const canSave = policy === "open" || anyProvider || requirePasskey || providerId != null;

  const save = () => {
    // What is being sent, so a choice changed while this is in flight is not
    // counted as saved by it.
    const sent = form.values;
    const rule: CommunityAuthPolicyUpdate =
      policy === "open"
        ? { policy: "open" }
        : {
            policy: "required",
            ...(anyProvider ? {} : { provider_id: providerId as number }),
            require_methods: [
              ...(anyProvider ? (["sso"] as const) : []),
              ...(requirePasskey ? (["passkey"] as const) : []),
            ],
          };
    updatePolicy.mutate(guest ? { guest_auth_policy: rule } : { auth_policy: rule }, {
      onSuccess: () => {
        setError(null);
        setUnmet(null);
        form.settle(sent);
        toast.success(t(`${copy}.saved`));
      },
      onError: (err: unknown) => {
        const detail = (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail;
        const method = unmetMethod(err);
        // The guests' rule is not asked of its writer, so only the members'
        // can be refused for this.
        if (!guest && detail === "AUTH_RULE_SELF_UNSATISFIED") {
          // A factor of the account's own is presented against the session
          // already open, so the prompt for it belongs here rather than at
          // a provider's sign-in page.
          if (method === "totp" || method === "passkey") {
            setUnmet({ kind: method });
            setError(null);
            return;
          }
          if (method === "provider" || method === "sso") {
            // "Any of ours" is satisfied by any of them, so offer the first.
            const chosen = anyProvider
              ? eligibleProviders[0]
              : eligibleProviders.find((entry) => entry.id === providerId);
            if (chosen) {
              setUnmet({ kind: "provider", slug: chosen.slug });
              setError(null);
              return;
            }
          }
          // A server that names no method, or a provider this page has no
          // name for: the refusal still gets its own line to stand on.
        }
        setUnmet(null);
        setError(getErrorMessage(err, `settings:${copy}.error`));
      },
    });
  };

  // The self-unsatisfied challenge is bound to the selection that produced
  // it: any change of policy or provider invalidates it (otherwise the
  // alert's button could name one provider while targeting another).
  const changePolicy = (value: "open" | "required") => {
    setPolicy(value);
    setUnmet(null);
    setError(null);
  };
  const changeProvider = (value: string) => {
    form.set(
      value === ANY_PROVIDER
        ? { anyProvider: true, providerId: null }
        : { anyProvider: false, providerId: Number(value) }
    );
    setUnmet(null);
    setError(null);
  };
  const changeRequirement = (patch: { requirePasskey?: boolean }) => {
    form.set(patch);
    setUnmet(null);
    setError(null);
  };

  // The public listing carries the community-addressed login URLs the
  // self-unsatisfied prompt sends the admin through.
  const loginProvidersQuery = useCommunityLoginProviders(communityId, {
    enabled: communityId > 0 && mayConfigureProviders && !guest,
  });

  const unmetProviderSlug = unmet?.kind === "provider" ? unmet.slug : null;
  const unmetFactor = unmet != null && unmet.kind !== "provider" ? unmet.kind : null;

  // Completing the required provider's sign-in updates this admin session's
  // satisfied set, after which saving the requirement succeeds.
  const signInWithRequiredProvider = () => {
    const entry = loginProvidersQuery.data?.providers.find((e) => e.slug === unmetProviderSlug);
    if (!entry) {
      return;
    }
    window.location.href = providerSignInHref(
      entry.login_url,
      `${window.location.pathname}${window.location.search}`
    );
  };
  const canSignInWithRequired =
    unmetProviderSlug != null &&
    loginProvidersQuery.data?.providers.some((e) => e.slug === unmetProviderSlug);

  // The same dialog every refused request opens, asked for here so a factor
  // is presented without leaving the page the requirement is being written on.
  const presentFactor = (kind: CommunityFactorKind) => {
    window.dispatchEvent(
      new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
        detail: { communityId, kind },
      })
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t(`${copy}.title`)}</CardTitle>
        <CardDescription>{t(`${copy}.description`)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <RadioGroup
          value={policy}
          onValueChange={(value) => changePolicy(value as "open" | "required")}
          className="gap-3"
        >
          <div className="flex items-start gap-3 rounded-md border px-4 py-3">
            <RadioGroupItem id={`${idPrefix}-open`} value="open" className="mt-1" />
            <div>
              <Label htmlFor={`${idPrefix}-open`} className="font-medium text-base">
                {t("communityAuth.policy.openLabel")}
              </Label>
              <p className="text-muted-foreground text-sm">{t(`${copy}.openHelp`)}</p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-md border px-4 py-3">
            <RadioGroupItem
              id={`${idPrefix}-required`}
              value="required"
              disabled={eligibleProviders.length === 0}
              className="mt-1"
            />
            <div className="min-w-0 flex-1 space-y-2">
              <Label htmlFor={`${idPrefix}-required`} className="font-medium text-base">
                {t("communityAuth.policy.requiredLabel")}
              </Label>
              <p className="text-muted-foreground text-sm">{t(`${copy}.requiredHelp`)}</p>
              {eligibleProviders.length === 0 ? (
                <p className="text-muted-foreground text-sm italic">
                  {t("communityAuth.policy.noProviders")}
                </p>
              ) : (
                policy === "required" && (
                  <Select
                    value={
                      anyProvider
                        ? ANY_PROVIDER
                        : providerId != null
                          ? String(providerId)
                          : undefined
                    }
                    onValueChange={changeProvider}
                  >
                    <SelectTrigger className="w-full max-w-72">
                      <SelectValue placeholder={t("communityAuth.policy.providerPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ANY_PROVIDER}>
                        {t("communityAuth.policy.anyProvider")}
                      </SelectItem>
                      {eligibleProviders.map((entry) => (
                        <SelectItem key={entry.id} value={String(entry.id)}>
                          {entry.display_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )
              )}
              {policy === "required" && anyProvider && (
                <p className="text-muted-foreground text-sm">{t(`${copy}.anyProviderHelp`)}</p>
              )}
            </div>
          </div>
        </RadioGroup>

        {policy === "required" && (
          <div className="flex items-start gap-3">
            <Checkbox
              id={`${idPrefix}-require-passkey`}
              checked={requirePasskey}
              onCheckedChange={(checked) => changeRequirement({ requirePasskey: Boolean(checked) })}
            />
            <div className="space-y-1">
              <Label htmlFor={`${idPrefix}-require-passkey`} className="font-medium">
                {t("communityAuth.policy.requirePasskey")}
              </Label>
              <p className="text-muted-foreground text-sm">{t(`${copy}.requirePasskeyHelp`)}</p>
            </div>
          </div>
        )}

        {unmetProviderSlug && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {t("communityAuth.policy.selfUnsatisfied", {
                  providerName: selectedProvider?.display_name ?? unmetProviderSlug,
                })}
              </span>
              {canSignInWithRequired && (
                <Button size="sm" onClick={signInWithRequiredProvider}>
                  {t("communityAuth.policy.signInWith", {
                    providerName: selectedProvider?.display_name ?? unmetProviderSlug,
                  })}
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
        {unmetFactor && (
          <Alert>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>{t(FACTOR_COPY[unmetFactor].line)}</span>
              <Button size="sm" onClick={() => presentFactor(unmetFactor)}>
                {t(FACTOR_COPY[unmetFactor].button)}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex justify-end">
          <Button
            onClick={save}
            disabled={!isDirty || !canSave || updatePolicy.isPending}
            // Two of these sit on the page, so the guests' one says which it saves.
            aria-label={guest ? t("communityAuth.guestPolicy.save") : undefined}
          >
            {updatePolicy.isPending ? t("common:submitting") : t("common:save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

/**
 * The longest a guest may stay. Blank leaves only the server's limit, which
 * also caps whatever is set here.
 */
const GuestStayCard = ({
  communityId,
  authSettings,
}: {
  communityId: number;
  authSettings: CommunityAuthSettingsRead;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const ceiling = authSettings.guest_max_days_by_platform;
  const form = useServerForm(
    authSettings,
    (loaded) => ({ days: loaded?.guest_max_days == null ? "" : String(loaded.guest_max_days) }),
    communityId
  );
  const update = useUpdateCommunityAuthSettings(communityId);
  const { value: days, valid } = readOptionalWholeNumber(form.values.days, 1, ceiling);
  const changed = days !== authSettings.guest_max_days;
  // Set for this community by whoever runs the server.
  const fixed = authSettings.set_by_deployment.includes("guest_max_days");

  const save = () => {
    const sent = form.values;
    update.mutate(
      { guest_max_days: days },
      {
        onSuccess: () => {
          form.settle(sent);
          toast.success(t("communityAuth.guestStay.saved"));
        },
        onError: (err: unknown) => {
          toast.error(getErrorMessage(err, "settings:communityAuth.guestStay.error"));
        },
      }
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityAuth.guestStay.title")}</CardTitle>
        <CardDescription>{t("communityAuth.guestStay.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Label htmlFor="community-guest-max-days">{t("communityAuth.guestStay.label")}</Label>
        <div className="flex flex-wrap items-center gap-3">
          <Input
            id="community-guest-max-days"
            type="number"
            min={1}
            max={ceiling}
            className="w-40"
            value={form.values.days}
            placeholder={String(ceiling)}
            disabled={fixed}
            onChange={(event) => form.set({ days: event.target.value })}
          />
          <Button
            onClick={save}
            disabled={fixed || !valid || !changed || update.isPending}
            aria-label={t("communityAuth.guestStay.save")}
          >
            {update.isPending ? t("common:submitting") : t("common:save")}
          </Button>
        </div>
        <p className="text-muted-foreground text-sm">
          {fixed
            ? t("communityAuth.setByDeployment")
            : t("communityAuth.guestStay.hint", { count: ceiling })}
        </p>
      </CardContent>
    </Card>
  );
};

export const SettingsCommunitySecurityPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const communityId = useActiveCommunityId();

  // What the operator has granted this community. The two halves of the page hang
  // off their own grant and are independent of each other: who gets in needs
  // ``providers``, the terms of a session need ``restrictions``. Outside both
  // the tab is hidden and a direct URL renders nothing (fail closed while
  // still loading).
  const { activeCommunity, refreshCommunities } = useCommunities();
  const hasGrantedSeat = activeCommunity?.grantSettingsLevel === "superadmin";
  // The seat above admin holds a community's sign-in configuration, and this
  // page is all of it — so it is theirs to reach, not only theirs to write.
  // The tab is gated the same way; this is the direct-URL half.
  const isSuperadmin = Boolean(activeCommunity?.can.seat);
  // Every control on the page reads from this one answer.
  const authSettings = useCommunityAuthSettings(communityId, {
    enabled: communityId > 0 && isSuperadmin,
  }).data;
  const grantedOptions = authSettings?.auth_options ?? [];
  const mayConfigureProviders = grantedOptions.includes("providers");
  const mayConfigureRestrictions = grantedOptions.includes("restrictions");
  const savedPolicy = authSettings?.auth_policy;
  // Where the deployment allows guests and the community takes them.
  const { guestsEnabled } = useAppConfig();
  const takesGuests = guestsEnabled && activeCommunity?.max_guests !== 0;
  // A requirement names a provider this community connects to, so the picker
  // reads the same list the registry below it edits.
  const connectionsQuery = useCommunityProviderConnections(communityId, {
    enabled: communityId > 0 && mayConfigureProviders,
  });
  // Only a live connection can be required. A disconnected or switched-off
  // one cannot serve a sign-in, and neither can one whose provider the
  // operator has since withdrawn.
  const eligibleProviders = useMemo(
    () =>
      (connectionsQuery.data ?? [])
        .filter((row) => row.enabled && row.login_ready)
        .map((row) => ({
          id: row.provider_id,
          slug: row.provider_slug,
          display_name: row.provider_display_name,
        })),
    [connectionsQuery.data]
  );
  const [wizardOpen, setWizardOpen] = useState(false);
  // Set when the wizard is opened to take over a provider the deployment
  // answered for, so it opens on that one rather than on the picker.
  const [wizardStartOn, setWizardStartOn] = useState<number | null>(null);

  // Each of these is one boolean, so each saves as it is switched.
  const updateSessionLimit = useUpdateCommunityAuthSettings(communityId);
  const sessionLimit = useFlipToSave(
    authSettings?.enforce_compliance_session ?? false,
    communityId
  );

  const { secondFactorAvailable } = useAppConfig();
  const updateSecondFactor = useUpdateCommunityAuthSettings(communityId);
  const secondFactor = useFlipToSave(authSettings?.require_second_factor ?? false, communityId);

  const changeSecondFactor = (next: boolean) => {
    secondFactor.begin(next);
    updateSecondFactor.mutate(
      { require_second_factor: next },
      {
        onSuccess: async () => {
          // A member's community list carries these too, for the pages that read
          // them there.
          if (!hasGrantedSeat) await refreshCommunities();
          secondFactor.settle();
          toast.success(t("communityAuth.secondFactor.saved"));
        },
        onError: (err: unknown) => {
          secondFactor.fail(getErrorMessage(err, "settings:communityAuth.secondFactor.error"));
        },
      }
    );
  };

  const changeSessionLimit = (next: boolean) => {
    sessionLimit.begin(next);
    updateSessionLimit.mutate(
      { enforce_compliance_session: next },
      {
        onSuccess: async () => {
          // A member's community list carries these too, for the pages that read
          // them there.
          if (!hasGrantedSeat) await refreshCommunities();
          sessionLimit.settle();
          toast.success(t("communityAuth.sessionLimit.saved"));
        },
        onError: (err: unknown) => {
          sessionLimit.fail(getErrorMessage(err, "settings:communityAuth.sessionLimit.error"));
        },
      }
    );
  };

  // Where the deployment already asks everybody for a second factor, this
  // community's own box has nothing to add, so it is not offered. A rule
  // already written stays on the row and comes back into force if the
  // deployment lowers its answer.
  // Where the deployment already asks everybody, this community's switch has
  // nothing to add, so it says so rather than offering the same answer twice.
  const factorAskedByPlatform = savedPolicy?.factor_required_by_platform === true;
  // What whoever runs the server sets for this community is shown, not offered.
  const setByDeployment = new Set(authSettings?.set_by_deployment ?? []);
  const factorFixed = setByDeployment.has("require_second_factor");
  const sessionLimitFixed = setByDeployment.has("enforce_compliance_session");
  // The community's shareable sign-in URL, built on the server's origin (which is
  // the app's own origin on web, or the configured server on native).
  const { getServerOrigin } = useServer();
  const urlBase = getServerOrigin() ?? window.location.origin;
  const memberLoginUrl = `${urlBase}/community/${communityId}/login`;
  const copyMemberLoginUrl = async () => {
    try {
      await navigator.clipboard.writeText(memberLoginUrl);
      toast.success(t("communityAuth.shareUrl.copied"));
    } catch (error) {
      console.error(error);
    }
  };

  // The page waits for its settings rather than reading "granted nothing" off
  // an answer that has not come back yet.
  if (
    !isSuperadmin ||
    authSettings == null ||
    (!mayConfigureProviders && !mayConfigureRestrictions)
  ) {
    return null;
  }

  return (
    <div className="space-y-10">
      {mayConfigureProviders ? (
        <section className="space-y-6">
          <h2 className="font-semibold text-xl tracking-tight">
            {t("communityAuth.sections.whoGetsIn")}
          </h2>

          <ConnectSignInWizard
            communityId={communityId}
            open={wizardOpen}
            onOpenChange={setWizardOpen}
            canRequire={mayConfigureProviders}
            startOn={wizardStartOn}
          />

          <CommunityAuthProvidersSection
            communityId={communityId}
            onConnect={(providerId) => {
              setWizardStartOn(providerId ?? null);
              setWizardOpen(true);
            }}
          />

          <CommunityClaimRulesSection communityId={communityId} />

          <SignInRequirementCard
            communityId={communityId}
            savedPolicy={savedPolicy}
            eligibleProviders={eligibleProviders}
            mayConfigureProviders={mayConfigureProviders}
          />
          {takesGuests ? (
            <SignInRequirementCard
              communityId={communityId}
              savedPolicy={authSettings.guest_auth_policy}
              eligibleProviders={eligibleProviders}
              mayConfigureProviders={mayConfigureProviders}
              guest
            />
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>{t("communityAuth.shareUrl.title")}</CardTitle>
              <CardDescription>{t("communityAuth.shareUrl.description")}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1.5 text-sm">
                {memberLoginUrl}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void copyMemberLoginUrl()}
              >
                {t("communityAuth.shareUrl.copy")}
              </Button>
            </CardContent>
          </Card>
        </section>
      ) : null}

      {mayConfigureRestrictions ? (
        <section className="space-y-6">
          <h2 className="font-semibold text-xl tracking-tight">
            {t("communityAuth.sections.onWhatTerms")}
          </h2>

          {secondFactorAvailable && (
            <Card>
              <CardHeader>
                <CardTitle>{t("communityAuth.secondFactor.title")}</CardTitle>
                <CardDescription>{t("communityAuth.secondFactor.description")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <Label htmlFor="community-second-factor" className="font-medium">
                      {t("communityAuth.secondFactor.allowLabel")}
                    </Label>
                    <p className="text-muted-foreground text-sm">
                      {factorAskedByPlatform
                        ? t("communityAuth.secondFactor.askedByPlatform")
                        : factorFixed
                          ? t("communityAuth.setByDeployment")
                          : t("communityAuth.secondFactor.help")}
                    </p>
                  </div>
                  <Switch
                    id="community-second-factor"
                    checked={secondFactor.value || factorAskedByPlatform}
                    onCheckedChange={changeSecondFactor}
                    disabled={updateSecondFactor.isPending || factorAskedByPlatform || factorFixed}
                  />
                </div>
                {secondFactor.error && (
                  <Alert variant="destructive">
                    <AlertDescription>{secondFactor.error}</AlertDescription>
                  </Alert>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>{t("communityAuth.sessionLimit.title")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <Label htmlFor="community-session-limit" className="font-medium">
                    {t("communityAuth.sessionLimit.allowLabel")}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {sessionLimitFixed
                      ? t("communityAuth.setByDeployment")
                      : t("communityAuth.sessionLimit.help")}
                  </p>
                </div>
                <Switch
                  id="community-session-limit"
                  checked={sessionLimit.value}
                  onCheckedChange={changeSessionLimit}
                  disabled={updateSessionLimit.isPending || sessionLimitFixed}
                />
              </div>
              {sessionLimit.error && (
                <Alert variant="destructive">
                  <AlertDescription>{sessionLimit.error}</AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          <CommunityNotificationPolicySection communityId={communityId} />

          <CommunityEngagementRankingSection communityId={communityId} />

          {takesGuests ? (
            <GuestStayCard communityId={communityId} authSettings={authSettings} />
          ) : null}
        </section>
      ) : null}
    </div>
  );
};
