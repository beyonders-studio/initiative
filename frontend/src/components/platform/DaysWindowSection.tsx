/**
 * Platform → Communities: one of the deployment's day-count windows — how long
 * a deleted community or account is kept, or how long a community stays on
 * hold before it is deleted.
 *
 * Each figure is the deployment's, one answer for everybody on the server.
 * Blank means never: nothing happens on a timer, and whatever the window
 * governs waits for somebody to act on it.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { useCommunitySettings, useUpdateCommunitySettings } from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { readOptionalWholeNumber } from "@/lib/text";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

const MIN_DAYS = 1;
const MAX_DAYS = 3650;

export type DaysWindowField =
  | "deleted_community_retention_days"
  | "deleted_account_retention_days"
  | "on_hold_community_deletion_days";

export interface DaysWindowSectionProps {
  field: DaysWindowField;
  /** The `settings` namespace group holding this window's strings. */
  i18nKey: "community.retention" | "community.accountRetention" | "community.holdDeletion";
  inputId: string;
  directoryEnabled: boolean;
}

export const DaysWindowSection = (props: DaysWindowSectionProps) => {
  const query = useCommunitySettings();
  if (!query.data) return null;

  // Mounted once the stored figure is known, so the box is not reset under
  // whoever is typing in it.
  return <DaysWindowForm {...props} days={query.data[props.field] ?? null} />;
};

const DaysWindowForm = ({
  field,
  i18nKey,
  inputId,
  directoryEnabled,
  days,
}: DaysWindowSectionProps & { days: number | null }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [value, setValue] = useState(days === null ? "" : String(days));
  const update = useUpdateCommunitySettings({
    onSuccess: (result) => {
      const saved = result[field] ?? null;
      toast.success(
        saved === null ? t(`${i18nKey}.savedNever`) : t(`${i18nKey}.saved`, { count: saved })
      );
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:community.saveError")),
  });

  const { value: parsed, valid } = readOptionalWholeNumber(value, MIN_DAYS, MAX_DAYS);
  const changed = parsed !== days;

  return (
    <SettingsSection title={t(`${i18nKey}.title`)} description={t(`${i18nKey}.description`)}>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t(`${i18nKey}.label`)} id={inputId} className="space-y-1">
          <Input
            type="number"
            min={MIN_DAYS}
            max={MAX_DAYS}
            className="w-40"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t(`${i18nKey}.placeholder`)}
          />
        </Field>
        <Button
          // Several of these sit on this page, so each says what it saves
          // rather than all being "Save" to anybody who cannot see which box it
          // is by.
          aria-label={t(`${i18nKey}.save`)}
          disabled={!valid || !changed || update.isPending}
          onClick={() =>
            update.mutate({
              // The endpoint writes the directory switch unconditionally, so
              // it is sent back as it stands rather than flipped by a save
              // about something else.
              community_directory_enabled: directoryEnabled,
              [field]: parsed,
            })
          }
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        {parsed === null ? t(`${i18nKey}.neverHint`) : t(`${i18nKey}.hint`)}
      </p>
    </SettingsSection>
  );
};
