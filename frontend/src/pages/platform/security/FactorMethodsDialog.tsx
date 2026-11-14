import { useTranslation } from "react-i18next";

import type {
  LoginMethod,
  PlatformAuthSettingsResponse,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow } from "@/components/settings/SettingsSection";
import { useServerForm } from "@/hooks/useServerForm";
import { useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Checkbox } from "@/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

import type { RuleDialogProps } from "./ruleDialog";

/** A second factor this page turns on and off. A passkey is also a way in,
 *  so it is set under Ways in and only shown here. */
const setHere = (entry: { answers_factor: boolean; primary: boolean }) =>
  entry.answers_factor && !entry.primary;

/**
 * Which second factors this server offers. Two things can answer being asked
 * for one, and the server says which (`answers_factor`) rather than this
 * keeping a list. Withdrawing one strands nobody, because it was never
 * anybody's only way in; leaving a standing requirement with nothing to
 * answer it is refused by the server with its own message.
 */
export const FactorMethodsDialog = ({
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
  const update = useUpdatePlatformAuthSettings(
    {
      onSuccess: () => {
        toast.success(t("auth.factorMethods.saved"));
        onOpenChange(false);
      },
    },
    "settings:auth.factorMethods.saveError"
  );

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
