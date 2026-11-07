/**
 * Platform → Security: who this deployment asks to hold a second factor.
 *
 * Three answers and one save. What satisfies it is the account holding a
 * factor — an authenticator or a passkey — or a session that presented one,
 * which is what an identity provider's own second factor looks like from
 * here. Which providers those are is the same per-provider answer the
 * registry holds, mirrored below so it is visible where the requirement is
 * set rather than a page away.
 *
 * Written here and enforced server-side, so what this page does is offer the
 * choice and state what it costs — never decide it.
 */

import { isAxiosError } from "axios";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import type { SecondFactorRequirement } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import {
  useAuthProviders,
  usePlatformAuthSettings,
  useUpdateAuthProvider,
  useUpdatePlatformAuthSettings,
} from "@/hooks/useSettings";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Alert, AlertDescription } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

/** The three answers, in the order they widen. */
const LEVELS = ["nobody", "platform_roles", "everyone"] as const;

export const SecondFactorRequirementSection = () => {
  const query = usePlatformAuthSettings();
  if (query.isLoading || !query.data) return null;

  // Mounted once the stored answer is known, so the choice is not reset
  // underneath whoever is reading it.
  return (
    <SecondFactorRequirementForm
      saved={query.data.second_factor_requirement}
      withoutFactor={query.data.accounts_without_factor}
      answerable={query.data.factor_methods_permitted}
    />
  );
};

const SecondFactorRequirementForm = ({
  saved,
  withoutFactor,
  answerable,
}: {
  saved: SecondFactorRequirement;
  withoutFactor: { platform_roles: number; everyone: number };
  /** Whether anything permitted could answer the requirement. With neither
   *  the authenticator app nor passkeys offered there is nothing to ask for,
   *  and the server refuses the write — so the controls say so first. */
  answerable: boolean;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const [choice, setChoice] = useState<SecondFactorRequirement>(saved);
  /** Set when the server refuses because this account does not meet the rule
   *  itself. Answered where they stand, by the dialog every refusal opens. */
  const [unmet, setUnmet] = useState(false);

  const update = useUpdatePlatformAuthSettings({
    onSuccess: () => {
      setUnmet(false);
      toast.success(t("auth.secondFactorRequirement.saved"));
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

  const change = (next: SecondFactorRequirement) => {
    setChoice(next);
    setUnmet(false);
  };

  /** How many accounts the chosen answer would ask to set one up. */
  const wouldAsk =
    choice === "everyone"
      ? withoutFactor.everyone
      : choice === "platform_roles"
        ? withoutFactor.platform_roles
        : 0;

  return (
    <SettingsSection
      title={t("auth.secondFactorRequirement.title")}
      description={t("auth.secondFactorRequirement.description")}
    >
      {!answerable && (
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.noMethod")}
        </p>
      )}
      <RadioGroup
        value={choice}
        onValueChange={(value) => change(value as SecondFactorRequirement)}
        className="gap-3"
        disabled={!answerable}
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

      {wouldAsk > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.wouldAsk", { count: wouldAsk })}
        </p>
      )}

      {choice !== "nobody" && (
        <p className="text-muted-foreground text-sm">
          {t("auth.secondFactorRequirement.derivedCredentials")}
        </p>
      )}

      <ProvidersThatCount />

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

      <div className="flex justify-end">
        <Button
          disabled={choice === saved || update.isPending || !answerable}
          onClick={() => update.mutate({ second_factor_requirement: choice })}
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
    </SettingsSection>
  );
};

/**
 * Which providers' own account of a sign-in answers this requirement.
 *
 * The same ``asserts_second_factor`` the registry holds, shown here because
 * this is where somebody decides who must hold a factor and therefore wants to
 * know who already does. Ticking either place writes the one answer.
 */
const ProvidersThatCount = () => {
  const { t } = useTranslation(["settings", "common"]);
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
