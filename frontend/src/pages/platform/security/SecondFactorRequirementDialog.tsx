import { isAxiosError } from "axios";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AUTH_FACTOR_REQUIRED_EVENT, type FactorChallengeDetail } from "@/api/client";
import type {
  PlatformAuthSettingsResponse,
  SecondFactorRequirement,
} from "@/api/generated/initiativeAPI.schemas";
import { WhenYouSave } from "@/components/settings/SettingsSection";
import { useServerForm } from "@/hooks/useServerForm";
import {
  useAuthProviders,
  useUpdateAuthProvider,
  useUpdatePlatformAuthSettings,
} from "@/hooks/useSettings";
import { getErrorCode, getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Alert, AlertDescription } from "@/ui/alert";
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
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

import type { RuleDialogProps } from "./ruleDialog";

/** Who has to hold a second factor, in the order the answers widen. */
const LEVELS = ["nobody", "platform_roles", "everyone"] as const;

/**
 * Who has to hold a second factor. What satisfies it is the account holding a
 * factor, or a session that presented one, which is what an identity
 * provider's own second factor looks like from here.
 */
export const SecondFactorRequirementDialog = ({
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
                updateProvider.mutate({
                  providerId: provider.id,
                  data: { asserts_second_factor: Boolean(checked) },
                })
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
