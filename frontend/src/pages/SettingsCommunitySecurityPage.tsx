import { type ReactNode, useMemo, useState } from "react";
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
  CommunityPeopleFigures,
} from "@/api/generated/initiativeAPI.schemas";
import { CommunityAuthProvidersSection } from "@/components/auth/CommunityAuthProvidersSection";
import { CommunityClaimRulesSection } from "@/components/auth/CommunityClaimRulesSection";
import { CommunityPrivacySection } from "@/components/auth/CommunityPrivacySection";
import { CustomRoleClaimRulesSection } from "@/components/auth/CustomRoleClaimRulesSection";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunities } from "@/hooks/useCommunities";
import {
  useCommunityAuthSettings,
  useCommunityLoginProviders,
  useCommunityProviderConnections,
  useUpdateCommunityAuthSettings,
} from "@/hooks/useCommunityAuthPolicy";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { providerSignInHref } from "@/lib/returnPath";
import { readOptionalWholeNumber } from "@/lib/text";
import { Alert, AlertDescription, AlertTitle } from "@/ui/alert";
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
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

/**
 * Community sign-in configuration (Settings → Security), in four sections.
 *
 * Sign-in rules are what somebody needs before they can open the community:
 * the members' and the guests' requirement — sessions reach this community
 * only after signing in through one specific provider, or any of its own;
 * `open` (the default) admits any signed-in session — a second factor, how
 * often members sign in again, and how long a guest may stay. Each row states
 * its current value and changes in a dialog that says who the change reaches.
 * Then the providers the community counts as its own, what the groups they
 * report mean here, and what leaves the community.
 */

/** The select's value for "any of ours" — a requirement that names no single
 * provider. Not a number, so it can never collide with a provider id. */
const ANY_PROVIDER = "any";

/** The rules a Sign-in rules row changes, by the setting each one writes. */
type SignInRule =
  | "auth_policy"
  | "require_second_factor"
  | "enforce_compliance_session"
  | "guest_auth_policy"
  | "guest_max_days";

type EligibleProvider = { id: number; slug: string; display_name: string };

/**
 * What this admin's own session is missing, when saving a rule is refused
 * because it does not meet the rule itself. The server names it; a provider is
 * answered by signing in again, a factor of the account's own by presenting it
 * here.
 */
type Unmet = { kind: "provider"; slug: string; name: string } | { kind: CommunityFactorKind };

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

/**
 * What a refused save says this session is missing, or null when the refusal
 * is about something else. A provider (or "any of ours") is answered by
 * `provider`; a server that names no method, or a provider this page has no
 * name for, leaves the refusal its own line to stand on.
 */
const readUnmet = (err: unknown, provider?: EligibleProvider): Unmet | null => {
  const response = (
    err as {
      response?: { data?: { detail?: string }; headers?: Record<string, unknown> };
    }
  ).response;
  if (response?.data?.detail !== "AUTH_RULE_SELF_UNSATISFIED") return null;
  // Axios lower-cases header keys.
  const method = response.headers?.["x-auth-policy-unmet"];
  if (method === "totp" || method === "passkey") return { kind: method };
  if ((method === "provider" || method === "sso") && provider) {
    return { kind: "provider", slug: provider.slug, name: provider.display_name };
  }
  return null;
};

/** The way to meet a refused rule from here: sign in through the provider it
 *  names, or present a factor without leaving the page. */
const UnmetAlert = ({ communityId, unmet }: { communityId: number; unmet: Unmet }) => {
  const { t } = useTranslation("settings");
  // The public listing carries the community-addressed login URLs.
  const loginProviders = useCommunityLoginProviders(communityId, {
    enabled: communityId > 0 && unmet.kind === "provider",
  });

  let line: string;
  let action: ReactNode = null;
  if (unmet.kind === "provider") {
    line = t("communityAuth.policy.selfUnsatisfied", { providerName: unmet.name });
    const entry = loginProviders.data?.providers.find((row) => row.slug === unmet.slug);
    if (entry) {
      // Completing the provider's sign-in adds it to this session, after
      // which saving the rule succeeds.
      action = (
        <Button
          size="sm"
          onClick={() => {
            window.location.href = providerSignInHref(
              entry.login_url,
              `${window.location.pathname}${window.location.search}`
            );
          }}
        >
          {t("communityAuth.policy.signInWith", { providerName: unmet.name })}
        </Button>
      );
    }
  } else {
    const kind = unmet.kind;
    line = t(FACTOR_COPY[kind].line);
    // The same dialog every refused request opens, asked for here so a
    // factor is presented without leaving the rule being written.
    action = (
      <Button
        size="sm"
        onClick={() =>
          window.dispatchEvent(
            new CustomEvent<FactorChallengeDetail>(AUTH_FACTOR_REQUIRED_EVENT, {
              detail: { communityId, kind },
            })
          )
        }
      >
        {t(FACTOR_COPY[kind].button)}
      </Button>
    );
  }

  return (
    <Alert>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
        <span>{line}</span>
        {action}
      </AlertDescription>
    </Alert>
  );
};

/** What a change reaches once it saves. Nothing to say, nothing shown. */
const WhenYouSave = ({ lines }: { lines: (string | false | null | undefined)[] }) => {
  const { t } = useTranslation("settings");
  const said = lines.filter((line): line is string => Boolean(line));
  if (said.length === 0) return null;
  return (
    <Alert role="note" className="border-transparent bg-muted">
      <AlertTitle>{t("communityAuth.whenYouSave")}</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-4">
          {said.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
};

/**
 * One sign-in requirement: the members' or, with `guest`, the guests'. The two
 * are set the same way; only the members' is asked of whoever saves it.
 */
const SignInRequirementDialog = ({
  communityId,
  communityName,
  open,
  onOpenChange,
  savedPolicy,
  eligibleProviders,
  figures,
  guest = false,
}: {
  communityId: number;
  communityName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  savedPolicy: CommunityAuthPolicyRead;
  eligibleProviders: EligibleProvider[];
  figures: CommunityPeopleFigures;
  guest?: boolean;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const copy = guest ? "communityAuth.guestPolicy" : "communityAuth.policy";
  const idPrefix = guest ? "guest-auth" : "community-auth";

  // Chosen here, saved by the footer — a refetch in between must not undo the
  // choice. Each opening starts from what is saved.
  const form = useServerForm(
    savedPolicy,
    (loaded) => ({
      policy: loaded?.policy ?? ("open" as "open" | "required"),
      providerId: loaded?.provider_id ?? null,
      // A rule that names no provider and asks for the community's own
      // single sign-on is the "any of ours" choice below.
      anyProvider: loaded?.provider_id == null && (loaded?.require_methods ?? []).includes("sso"),
      // Orthogonal to the provider choice: a community may ask for its own
      // sign-in, for a passkey, or for both.
      requirePasskey: (loaded?.require_methods ?? []).includes("passkey"),
    }),
    [open, communityId]
  );
  const { policy, providerId, anyProvider, requirePasskey } = form.values;
  const [error, setError] = useState<string | null>(null);
  const [unmet, setUnmet] = useState<Unmet | null>(null);
  const updatePolicy = useUpdateCommunityAuthSettings(communityId);

  const close = () => {
    onOpenChange(false);
    setError(null);
    setUnmet(null);
  };

  const selectedProvider = eligibleProviders.find((entry) => entry.id === providerId);
  const savedAnyProvider =
    savedPolicy.provider_id == null && savedPolicy.require_methods.includes("sso");
  const savedRequirePasskey = savedPolicy.require_methods.includes("passkey");
  const isDirty =
    policy !== savedPolicy.policy ||
    (policy === "required" &&
      (anyProvider !== savedAnyProvider ||
        requirePasskey !== savedRequirePasskey ||
        (!anyProvider && providerId !== (savedPolicy.provider_id ?? null))));
  // A rule has to ask for something. Any one of the three will do.
  const canSave = policy === "open" || anyProvider || requirePasskey || providerId != null;

  // The self-unsatisfied challenge is bound to the selection that produced
  // it: any change invalidates it (otherwise the alert's button could name
  // one provider while targeting another).
  const change = (patch: Partial<typeof form.values>) => {
    form.set(patch);
    setUnmet(null);
    setError(null);
  };

  const save = () => {
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
        toast.success(t(`${copy}.saved`));
        close();
      },
      onError: (err: unknown) => {
        // The guests' rule is not asked of its writer, so only the members'
        // can be refused for this. "Any of ours" is met by any of them, so
        // the first is offered.
        const found = guest
          ? null
          : readUnmet(err, anyProvider ? eligibleProviders[0] : selectedProvider);
        setUnmet(found);
        setError(found ? null : getErrorMessage(err, `settings:${copy}.error`));
      },
    });
  };

  // Who the rule reaches, read off the counts of people who have never met it.
  const neverThrough = anyProvider
    ? figures.never_through_any
    : (figures.never_through.find((row) => row.provider_id === providerId)?.count ?? 0);
  const provider = selectedProvider?.display_name ?? "";
  const impact =
    policy === "required" && canSave
      ? [
          selectedProvider
            ? t(`${copy}.impact.provider`, { provider, community: communityName })
            : anyProvider
              ? t(`${copy}.impact.anyProvider`, { community: communityName })
              : t(`${copy}.impact.passkey`, { community: communityName }),
          !guest &&
            (selectedProvider
              ? t("communityAuth.policy.impact.selfProvider", { provider })
              : t("communityAuth.policy.impact.selfOther")),
          neverThrough > 0 &&
            (anyProvider
              ? t(`${copy}.impact.neverThroughAny`, {
                  count: neverThrough,
                  total: figures.total,
                })
              : selectedProvider &&
                t(`${copy}.impact.neverThrough`, {
                  count: neverThrough,
                  total: figures.total,
                  provider,
                })),
          requirePasskey &&
            figures.without_passkey > 0 &&
            t(`${copy}.impact.noPasskey`, {
              count: figures.without_passkey,
              total: figures.total,
            }),
        ]
      : [];

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(`${copy}.title`)}</DialogTitle>
          <DialogDescription>
            {t(`${copy}.description`, { community: communityName })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RadioGroup
            value={policy}
            onValueChange={(value) => change({ policy: value as "open" | "required" })}
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
            {eligibleProviders.length > 0 && (
              <div className="flex items-start gap-3 rounded-md border px-4 py-3">
                <RadioGroupItem id={`${idPrefix}-required`} value="required" className="mt-1" />
                <div className="min-w-0 flex-1 space-y-2">
                  <Label htmlFor={`${idPrefix}-required`} className="font-medium text-base">
                    {t("communityAuth.policy.requiredLabel")}
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    {t("communityAuth.policy.requiredHelp")}
                  </p>
                  {policy === "required" && (
                    <Select
                      value={
                        anyProvider
                          ? ANY_PROVIDER
                          : providerId != null
                            ? String(providerId)
                            : undefined
                      }
                      onValueChange={(value) =>
                        change(
                          value === ANY_PROVIDER
                            ? { anyProvider: true, providerId: null }
                            : { anyProvider: false, providerId: Number(value) }
                        )
                      }
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
                  )}
                  {policy === "required" && anyProvider && (
                    <p className="text-muted-foreground text-sm">{t(`${copy}.anyProviderHelp`)}</p>
                  )}
                </div>
              </div>
            )}
          </RadioGroup>
          {eligibleProviders.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("communityAuth.policy.noProviders")}</p>
          )}

          {policy === "required" && (
            <div className="flex items-start gap-3">
              <Checkbox
                id={`${idPrefix}-require-passkey`}
                checked={requirePasskey}
                onCheckedChange={(checked) => change({ requirePasskey: Boolean(checked) })}
              />
              <div className="space-y-1">
                <Label htmlFor={`${idPrefix}-require-passkey`} className="font-medium">
                  {t("communityAuth.policy.requirePasskey")}
                </Label>
                <p className="text-muted-foreground text-sm">{t(`${copy}.requirePasskeyHelp`)}</p>
              </div>
            </div>
          )}

          <WhenYouSave lines={impact} />
          {unmet && <UnmetAlert communityId={communityId} unmet={unmet} />}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter
          submitLabel={t("communityAuth.policy.save")}
          pending={updatePolicy.isPending}
          disabled={!isDirty || !canSave}
          onSubmit={save}
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * A rule that is on or off: the second factor, or signing in again every
 * twelve hours. Turning one on says who it reaches before it saves.
 */
const OnOffRuleDialog = ({
  communityId,
  rule,
  saved,
  impact,
  open,
  onOpenChange,
}: {
  communityId: number;
  rule: "require_second_factor" | "enforce_compliance_session";
  saved: boolean;
  /** What turning it on reaches, a line each. */
  impact: (string | false)[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const { activeCommunity, refreshCommunities } = useCommunities();
  const copy =
    rule === "require_second_factor" ? "communityAuth.secondFactor" : "communityAuth.sessionLimit";
  const form = useServerForm(saved, (loaded) => ({ on: loaded ?? false }), [open, communityId]);
  const [error, setError] = useState<string | null>(null);
  const [unmet, setUnmet] = useState<Unmet | null>(null);
  const update = useUpdateCommunityAuthSettings(communityId);

  const close = () => {
    onOpenChange(false);
    setError(null);
    setUnmet(null);
  };

  const save = () =>
    update.mutate(
      rule === "require_second_factor"
        ? { require_second_factor: form.values.on }
        : { enforce_compliance_session: form.values.on },
      {
        onSuccess: async () => {
          // A member's community list carries these too, for the pages that
          // read them there.
          if (activeCommunity?.grantSettingsLevel !== "superadmin") await refreshCommunities();
          toast.success(t(`${copy}.saved`));
          close();
        },
        onError: (err: unknown) => {
          const found = readUnmet(err);
          setUnmet(found);
          setError(found ? null : getErrorMessage(err, `settings:${copy}.error`));
        },
      }
    );

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(`${copy}.title`)}</DialogTitle>
          <DialogDescription>
            {t(`${copy}.description`, { community: activeCommunity?.name ?? "" })}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <RadioGroup
            value={form.values.on ? "on" : "off"}
            onValueChange={(value) => {
              form.set({ on: value === "on" });
              setUnmet(null);
              setError(null);
            }}
            className="gap-3"
          >
            {(["off", "on"] as const).map((value) => (
              <div key={value} className="flex items-center gap-3 rounded-md border px-4 py-3">
                <RadioGroupItem id={`${rule}-${value}`} value={value} />
                <Label htmlFor={`${rule}-${value}`} className="font-medium text-base">
                  {value === "on" ? t(`${copy}.onLabel`) : t(`${copy}.offLabel`)}
                </Label>
              </div>
            ))}
          </RadioGroup>
          {/* Only turning a rule on reaches anybody; turning it off just saves. */}
          <WhenYouSave lines={form.values.on && !saved ? impact : []} />
          {unmet && <UnmetAlert communityId={communityId} unmet={unmet} />}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={form.values.on === saved}
          onSubmit={save}
        />
      </DialogContent>
    </Dialog>
  );
};

/**
 * The longest a guest may stay. Blank leaves only the server's limit, which
 * also caps whatever is set here.
 */
const GuestStayDialog = ({
  communityId,
  authSettings,
  open,
  onOpenChange,
}: {
  communityId: number;
  authSettings: CommunityAuthSettingsRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const ceiling = authSettings.guest_max_days_by_platform;
  const form = useServerForm(
    authSettings,
    (loaded) => ({ days: loaded?.guest_max_days == null ? "" : String(loaded.guest_max_days) }),
    [open, communityId]
  );
  const update = useUpdateCommunityAuthSettings(communityId);
  const { value: days, valid } = readOptionalWholeNumber(form.values.days, 1, ceiling);

  const save = () =>
    update.mutate(
      { guest_max_days: days },
      {
        onSuccess: () => {
          toast.success(t("communityAuth.guestStay.saved"));
          onOpenChange(false);
        },
        onError: (err: unknown) => {
          toast.error(getErrorMessage(err, "settings:communityAuth.guestStay.error"));
        },
      }
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("communityAuth.guestStay.title")}</DialogTitle>
          <DialogDescription>{t("communityAuth.guestStay.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="community-guest-max-days">{t("communityAuth.guestStay.label")}</Label>
          <Input
            id="community-guest-max-days"
            type="number"
            min={1}
            max={ceiling}
            className="w-40"
            value={form.values.days}
            placeholder={String(ceiling)}
            onChange={(event) => form.set({ days: event.target.value })}
          />
          <p className="text-muted-foreground text-sm">
            {t("communityAuth.guestStay.hint", { count: ceiling })}
          </p>
        </div>
        <DialogFooter
          submitLabel={t("common:save")}
          pending={update.isPending}
          disabled={!valid || days === authSettings.guest_max_days}
          onSubmit={save}
        />
      </DialogContent>
    </Dialog>
  );
};

export const SettingsCommunitySecurityPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const communityId = useActiveCommunityId();

  // What the operator has granted this community. The sections hang off their
  // own grant and are independent of each other: the providers, the groups
  // and the requirements naming them need ``providers``, the other rules and
  // privacy need ``restrictions``. Outside both the tab is hidden and a direct
  // URL renders nothing (fail closed while still loading).
  const { activeCommunity } = useCommunities();
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
  // Where the deployment allows guests and the community takes them.
  const { guestsEnabled, secondFactorAvailable } = useAppConfig();
  const takesGuests = guestsEnabled && activeCommunity?.max_guests !== 0;
  // A requirement names a provider this community connects to, so the picker
  // reads the same list the providers section edits.
  const connectionsQuery = useCommunityProviderConnections(communityId, {
    enabled: communityId > 0 && mayConfigureProviders,
  });
  const connections = connectionsQuery.data ?? [];
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
  const [changing, setChanging] = useState<SignInRule | null>(null);

  // The page waits for its settings rather than reading "granted nothing" off
  // an answer that has not come back yet.
  if (
    !isSuperadmin ||
    authSettings == null ||
    (!mayConfigureProviders && !mayConfigureRestrictions)
  ) {
    return null;
  }

  const communityName = activeCommunity?.name ?? "";
  // What whoever runs the server sets for this community is shown, not offered.
  const setByDeployment = new Set(authSettings.set_by_deployment);
  // Where the deployment already asks everybody for a second factor, this
  // community's rule has nothing to add. A rule already written stays and
  // comes back into force if the deployment lowers its answer.
  const factorAskedByPlatform = authSettings.auth_policy.factor_required_by_platform;
  const factorRequired = authSettings.require_second_factor || factorAskedByPlatform;
  const sessionLimit = authSettings.enforce_compliance_session;
  const ceiling = authSettings.guest_max_days_by_platform;

  const describePolicy = (policy: CommunityAuthPolicyRead): string => {
    if (policy.policy === "open") return t("communityAuth.policy.openLabel");
    const passkey = policy.require_methods.includes("passkey");
    const provider = policy.provider_display_name ?? policy.provider_slug;
    if (provider) {
      return passkey
        ? t("communityAuth.policy.value.throughWithPasskey", { provider })
        : t("communityAuth.policy.value.through", { provider });
    }
    if (policy.require_methods.includes("sso")) {
      return passkey
        ? t("communityAuth.policy.value.anyWithPasskey")
        : t("communityAuth.policy.value.any");
    }
    return t("communityAuth.policy.value.passkey");
  };

  const rules: {
    key: SignInRule;
    shown: boolean;
    label: string;
    value: string;
    detail?: string | null;
    fixed?: boolean;
  }[] = [
    {
      key: "auth_policy",
      shown: mayConfigureProviders,
      label: t("communityAuth.signInRules.members"),
      value: describePolicy(authSettings.auth_policy),
    },
    {
      key: "require_second_factor",
      shown: mayConfigureRestrictions && secondFactorAvailable,
      label: t("communityAuth.secondFactor.title"),
      value: factorRequired
        ? t("communityAuth.secondFactor.onLabel")
        : t("communityAuth.secondFactor.offLabel"),
      detail: factorRequired && takesGuests ? t("communityAuth.secondFactor.guestsToo") : null,
      fixed: factorAskedByPlatform,
    },
    {
      key: "enforce_compliance_session",
      shown: mayConfigureRestrictions,
      label: t("communityAuth.sessionLimit.title"),
      value: sessionLimit ? t("communityAuth.on") : t("communityAuth.off"),
      detail: sessionLimit
        ? t("communityAuth.sessionLimit.onDetail")
        : t("communityAuth.sessionLimit.offDetail"),
    },
    {
      key: "guest_auth_policy",
      shown: mayConfigureProviders && takesGuests,
      label: t("communityAuth.signInRules.guests"),
      value: describePolicy(authSettings.guest_auth_policy),
    },
    {
      key: "guest_max_days",
      shown: mayConfigureRestrictions && takesGuests,
      label: t("communityAuth.guestStay.title"),
      value: t("communityAuth.guestStay.value", { count: authSettings.guest_max_days ?? ceiling }),
      detail:
        authSettings.guest_max_days == null
          ? t("communityAuth.guestStay.defaultDetail")
          : t("communityAuth.guestStay.ceilingDetail", { days: ceiling }),
    },
  ];

  // Everybody who opens the community, guests included, is asked for a factor.
  const withoutFactor =
    authSettings.member_figures.without_factor + authSettings.guest_figures.without_factor;
  const people = authSettings.member_figures.total + authSettings.guest_figures.total;
  const closeDialog = (open: boolean) => {
    if (!open) setChanging(null);
  };

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">
        {t("communityAuth.intro", { community: communityName })}
      </p>

      <SettingsSection
        title={t("communityAuth.signInRules.title")}
        description={t("communityAuth.signInRules.description", { community: communityName })}
      >
        {rules
          .filter((rule) => rule.shown)
          .map((rule) => (
            <SettingsRow
              key={rule.key}
              label={rule.label}
              description={
                <>
                  <span className="text-foreground">{rule.value}</span>
                  {rule.detail ? ` · ${rule.detail}` : null}
                </>
              }
            >
              {rule.fixed || setByDeployment.has(rule.key) ? (
                <Badge variant="secondary">{t("communityAuth.setByServer")}</Badge>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label={t("communityAuth.changeRule", { rule: rule.label })}
                  onClick={() => setChanging(rule.key)}
                >
                  {t("communityAuth.change")}
                </Button>
              )}
            </SettingsRow>
          ))}
      </SettingsSection>

      <SignInRequirementDialog
        communityId={communityId}
        communityName={communityName}
        open={changing === "auth_policy"}
        onOpenChange={closeDialog}
        savedPolicy={authSettings.auth_policy}
        eligibleProviders={eligibleProviders}
        figures={authSettings.member_figures}
      />
      <SignInRequirementDialog
        communityId={communityId}
        communityName={communityName}
        open={changing === "guest_auth_policy"}
        onOpenChange={closeDialog}
        savedPolicy={authSettings.guest_auth_policy}
        eligibleProviders={eligibleProviders}
        figures={authSettings.guest_figures}
        guest
      />
      <OnOffRuleDialog
        communityId={communityId}
        rule="require_second_factor"
        saved={authSettings.require_second_factor}
        impact={[
          t("communityAuth.secondFactor.impact", { community: communityName }),
          withoutFactor > 0 &&
            t("communityAuth.secondFactor.withoutFactor", { count: withoutFactor, total: people }),
        ]}
        open={changing === "require_second_factor"}
        onOpenChange={closeDialog}
      />
      <OnOffRuleDialog
        communityId={communityId}
        rule="enforce_compliance_session"
        saved={sessionLimit}
        impact={[t("communityAuth.sessionLimit.impact")]}
        open={changing === "enforce_compliance_session"}
        onOpenChange={closeDialog}
      />
      <GuestStayDialog
        communityId={communityId}
        authSettings={authSettings}
        open={changing === "guest_max_days"}
        onOpenChange={closeDialog}
      />

      {mayConfigureProviders ? (
        <CommunityAuthProvidersSection communityId={communityId} communityName={communityName} />
      ) : null}

      {/* A group rule names a provider, so there is nothing to write one
          against until something is connected. */}
      {mayConfigureProviders && connections.length > 0 ? (
        <SettingsSection
          title={t("communityAuth.groupRules.title")}
          description={t("communityAuth.groupRules.description")}
        >
          <CommunityClaimRulesSection communityId={communityId} />
          <CustomRoleClaimRulesSection communityId={communityId} />
        </SettingsSection>
      ) : null}

      {mayConfigureRestrictions ? (
        <CommunityPrivacySection
          communityId={communityId}
          communityName={communityName}
          settings={authSettings}
        />
      ) : null}
    </div>
  );
};
