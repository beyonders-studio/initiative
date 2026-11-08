import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityAuthPolicyRead,
  CommunityAuthPolicyUpdate,
  CommunityPeopleFigures,
} from "@/api/generated/initiativeAPI.schemas";
import { WhenYouSave } from "@/components/settings/SettingsSection";
import { useUpdateCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { useServerForm } from "@/hooks/useServerForm";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Alert, AlertDescription } from "@/ui/alert";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

import { type EligibleProvider, readUnmet, type Unmet, UnmetAlert } from "./UnmetAlert";

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

/**
 * One sign-in requirement: the members' or, with `guest`, the guests'. The two
 * are set the same way; only the members' is asked of whoever saves it.
 */
export const SignInRequirementDialog = ({
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
      <DialogContent className="sm:max-w-lg">
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
