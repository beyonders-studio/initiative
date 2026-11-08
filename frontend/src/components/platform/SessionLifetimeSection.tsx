/**
 * Platform → Security: how long somebody may stay signed in before signing in
 * again.
 *
 * A different question from how long a session may be left alone, which the
 * deployment's configuration holds: this one nothing pushes forward. Blank
 * asks for no limit, which is where a self-hosted deployment starts.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { usePlatformAuthSettings, useUpdatePlatformAuthSettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { readOptionalWholeNumber } from "@/lib/text";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

export const SessionLifetimeSection = () => {
  const query = usePlatformAuthSettings();
  if (query.isLoading || !query.data) return null;

  // The field starts from the stored figure, so the form is mounted once that
  // figure is known rather than reset underneath whoever is typing.
  return (
    <SessionLifetimeForm
      hours={query.data.session_max_hours ?? null}
      idleMinutes={query.data.session_idle_minutes ?? null}
    />
  );
};

const SessionLifetimeForm = ({
  hours,
  idleMinutes,
}: {
  hours: number | null;
  idleMinutes: number | null;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const [value, setValue] = useState(hours === null ? "" : String(hours));
  const [idle, setIdle] = useState(idleMinutes === null ? "" : String(idleMinutes));
  const update = useUpdatePlatformAuthSettings({
    onSuccess: () => toast.success(t("auth.sessionLifetime.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.sessionLifetime.error")),
  });

  const maxHours = readOptionalWholeNumber(value, 1);
  const idleLimit = readOptionalWholeNumber(idle, 1);
  const valid = maxHours.valid && idleLimit.valid;
  // Saved together, because they are two halves of one answer and the server
  // takes them in one write.
  const changed = maxHours.value !== hours || idleLimit.value !== idleMinutes;

  return (
    <SettingsSection
      title={t("auth.sessionLifetime.title")}
      description={t("auth.sessionLifetime.description")}
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("auth.sessionLifetime.label")} className="space-y-1">
          <Input
            type="number"
            min={1}
            className="w-40"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t("auth.sessionLifetime.placeholder")}
          />
        </Field>
        <Field label={t("auth.sessionLifetime.idleLabel")} className="space-y-1">
          <Input
            type="number"
            min={1}
            className="w-40"
            value={idle}
            onChange={(event) => setIdle(event.target.value)}
            placeholder={t("auth.sessionLifetime.idlePlaceholder")}
          />
        </Field>
        <Button
          disabled={!valid || !changed || update.isPending}
          onClick={() =>
            update.mutate({
              session_max_hours: maxHours.value,
              session_idle_minutes: idleLimit.value,
            })
          }
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("auth.sessionLifetime.hint")}</p>
      <p className="text-muted-foreground text-xs">{t("auth.sessionLifetime.idleHint")}</p>
    </SettingsSection>
  );
};
