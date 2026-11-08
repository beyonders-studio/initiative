import { keepPreviousData } from "@tanstack/react-query";
import { Dices } from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSuggestUsernames } from "@/api/generated/auth/auth";
import { type HandleCheck, UsernameField } from "@/components/account/UsernameField";
import { BirthdateField } from "@/components/auth/BirthdateField";
import type { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { ContinueButton } from "@/components/start/stepParts";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { Button } from "@/ui/button";
import { Combobox } from "@/ui/combobox";
import { Field } from "@/ui/field";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";

/** How long typing settles before the suggestions start from it. */
const SEED_SETTLES_MS = 400;

/** Names nobody holds yet, starting from what is typed, to tap into the field. */
const HandleSuggestions = ({
  typed,
  current,
  onPick,
  disabled,
}: {
  typed: string;
  current: string;
  onPick: (name: string) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  const seed = useDebouncedValue(typed.trim(), SEED_SETTLES_MS);
  const { data } = useSuggestUsernames(seed ? { seed } : undefined, {
    query: { placeholderData: keepPreviousData, retry: false },
  });
  const names = (data?.suggestions ?? []).filter((name) => name !== current.trim());
  if (!names.length) return null;
  return (
    <fieldset>
      <legend className="mb-1.5 text-muted-foreground text-xs">{t("start.you.suggestions")}</legend>
      <div className="flex flex-wrap gap-2">
        {names.map((name) => (
          <Button
            key={name}
            type="button"
            size="sm"
            variant="outline"
            className="rounded-full border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 hover:text-emerald-800 dark:text-emerald-300 dark:hover:text-emerald-200"
            onClick={() => onPick(name)}
            disabled={disabled}
          >
            <Dices className="h-3.5 w-3.5" aria-hidden="true" />
            {name}
          </Button>
        ))}
      </div>
    </fieldset>
  );
};

/**
 * Who they are. Signed out that is the handle (required), the timezone, and
 * the birthdate where the deployment asks; signed in it is only ever the
 * birthdate, for joining.
 */
export const YouStep = ({
  signedIn,
  username,
  onUsernameChange,
  onHandleOffer,
  timezone,
  onTimezoneChange,
  age,
  asksAge,
  ageRequired,
  busy,
  onContinue,
}: {
  signedIn: boolean;
  username: string;
  onUsernameChange: (username: string) => void;
  /** The signed number shown beside the handle, sent with the account. */
  onHandleOffer: (offer: string | null) => void;
  timezone: string;
  onTimezoneChange: (timezone: string) => void;
  age: ReturnType<typeof useAgeConfirmation>;
  asksAge: boolean;
  ageRequired: boolean;
  busy: boolean;
  onContinue: () => void;
}) => {
  const { t } = useTranslation(["auth", "settings"]);
  const [handleUsable, setHandleUsable] = useState(true);
  // Suggestions start from what was typed, so picking one does not seed the
  // next round from the pick.
  const [typed, setTyped] = useState(username);
  const onChecked = useCallback(
    (check: HandleCheck) => {
      setHandleUsable(check.usable);
      onHandleOffer(check.offer);
    },
    [onHandleOffer]
  );
  const handleMissing = !signedIn && (!username.trim() || !handleUsable);
  return (
    <>
      {signedIn ? null : (
        <>
          <div className="space-y-2">
            <UsernameField
              id="start-username"
              value={username}
              onChange={(name) => {
                setTyped(name);
                onUsernameChange(name);
              }}
              onChecked={onChecked}
              disabled={busy}
            />
            <HandleSuggestions
              typed={typed}
              current={username}
              onPick={onUsernameChange}
              disabled={busy}
            />
          </div>
          <Field label={t("settings:profile.timezoneLabel")}>
            <Combobox
              items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
              value={timezone}
              onValueChange={onTimezoneChange}
              placeholder={t("settings:profile.timezonePlaceholder")}
              emptyMessage={t("settings:profile.timezoneEmpty")}
            />
          </Field>
        </>
      )}
      {asksAge ? (
        <BirthdateField
          id="start-birthdate"
          value={age.birthdate}
          onChange={age.setBirthdate}
          disabled={busy || age.submitting}
        />
      ) : null}
      {age.error ? <p className="text-destructive text-sm">{age.error}</p> : null}
      <ContinueButton
        onClick={onContinue}
        disabled={busy || age.submitting || handleMissing || (ageRequired && !age.birthdate)}
      />
    </>
  );
};
