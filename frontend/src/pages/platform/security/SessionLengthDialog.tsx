import { useTranslation } from "react-i18next";

import type { PlatformAuthSettingsResponse } from "@/api/generated/initiativeAPI.schemas";
import { useServerForm } from "@/hooks/useServerForm";
import { useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { readOptionalWholeNumber } from "@/lib/text";
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

import type { RuleDialogProps } from "./ruleDialog";

/**
 * How long somebody may stay signed in before signing in again, and how long
 * a session may sit untouched. Saved together, because they are two halves of
 * one answer and the server takes them in one write. Blank asks for no limit,
 * which is where a self-hosted deployment starts.
 */
export const SessionLengthDialog = ({
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
  const update = useUpdatePlatformAuthSettings(
    {
      onSuccess: () => {
        toast.success(t("auth.sessionLifetime.saved"));
        onOpenChange(false);
      },
    },
    "settings:auth.sessionLifetime.error"
  );

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
