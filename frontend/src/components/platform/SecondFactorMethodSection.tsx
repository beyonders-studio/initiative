/**
 * Platform → Security: which second factors this server offers.
 *
 * Two things can answer being asked for one, and the server says which
 * (`answers_factor`) rather than this keeping a list.
 *
 * A passkey is both a way in and an answer to being asked for a factor, so it
 * appears here *and* under Ways in — but it is governed in one place only.
 * Its row here reflects that decision and cannot be toggled from this side;
 * two checkboxes writing one bit would let the page contradict itself. The
 * authenticator app is nothing but a second factor, so this is where it is
 * turned on and off.
 *
 * No acknowledgement dialog, unlike the ways in: withdrawing a second factor
 * strands nobody, because it was never anybody's only way to sign in. What it
 * can do is leave a standing requirement with nothing to answer it, and the
 * server refuses that with its own message.
 */

import { useTranslation } from "react-i18next";

import type { LoginMethod } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { usePlatformAuthSettings, useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Checkbox } from "@/ui/checkbox";
import { Label } from "@/ui/label";

export const SecondFactorMethodSection = () => {
  const { t } = useTranslation("settings");
  const query = usePlatformAuthSettings();

  const updateMethods = useUpdatePlatformAuthSettings({
    onSuccess: () => toast.success(t("auth.factorMethods.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.factorMethods.saveError")),
  });

  if (query.isLoading || !query.data) return null;

  const { methods } = query.data;
  const factors = methods.filter((entry) => entry.answers_factor);
  if (factors.length === 0) return null;

  const enabled = methods.filter((m) => m.enabled).map((m) => m.method);
  const busy = updateMethods.isPending;

  const toggleMethod = (method: LoginMethod, checked: boolean) =>
    updateMethods.mutate({
      methods: checked ? [...enabled, method] : enabled.filter((m) => m !== method),
    });

  return (
    <SettingsSection
      title={t("auth.factorMethods.title")}
      description={t("auth.factorMethods.description")}
    >
      <div className="space-y-4">
        {factors.map((entry) => {
          // Decided under Ways in, where it is a way in. Shown here so the
          // answer to "what can answer this" is complete, and read-only so
          // there is one place it is set.
          const decidedElsewhere = entry.primary;
          return (
            <div key={entry.method} className="flex items-start gap-3">
              <Checkbox
                id={`factor-method-${entry.method}`}
                checked={entry.enabled}
                disabled={busy || decidedElsewhere}
                onCheckedChange={(checked) =>
                  !decidedElsewhere && toggleMethod(entry.method, Boolean(checked))
                }
                className="mt-0.5"
              />
              <div className="space-y-1">
                <Label
                  htmlFor={`factor-method-${entry.method}`}
                  className={decidedElsewhere ? "font-medium" : "cursor-pointer font-medium"}
                >
                  {t(`auth.methods.${entry.method}.label`)}
                </Label>
                <p className="text-muted-foreground text-sm">
                  {decidedElsewhere
                    ? t("auth.factorMethods.followsWaysIn")
                    : t(`auth.methods.${entry.method}.help`)}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </SettingsSection>
  );
};
