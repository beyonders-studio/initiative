import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { checkUsernameAvailable } from "@/api/generated/auth/auth";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";

/** What the check said about the name typed so far. */
export interface HandleCheck {
  /** False while the name is being checked, and after the server refused it. */
  usable: boolean;
  /** The signed number shown beside the name, sent with the account so it
   *  gets that number. */
  offer: string | null;
}

interface UsernameFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Seeds the field the first time the person types a name, if it is empty. */
  suggestion?: string;
  disabled?: boolean;
  id?: string;
  onChecked?: (check: HandleCheck) => void;
}

type Availability =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "available"; discriminator: number | null; offer: string | null }
  | { state: "taken"; reason: string };

/**
 * The name part of a handle, with the number it will get shown beside it,
 * locked: the server picks the number and the account keeps it.
 *
 * A name is almost always free, since ten thousand numbers sit behind each
 * one, so this says no only for a reserved or malformed name, or the rare one
 * whose numbers are all spoken for.
 */
export const UsernameField = ({
  value,
  onChange,
  suggestion,
  disabled,
  id = "username",
  onChecked,
}: UsernameFieldProps) => {
  const { t } = useTranslation("auth");
  const { t: tErrors } = useTranslation("errors");
  const [availability, setAvailability] = useState<Availability>({ state: "idle" });
  const [touched, setTouched] = useState(false);

  // Seed from the name they already typed, until they edit the field
  // themselves; after that it is theirs.
  useEffect(() => {
    if (!touched && suggestion && !value) onChange(suggestion);
  }, [suggestion, touched, value, onChange]);

  useEffect(() => {
    const candidate = value.trim();
    if (!candidate) {
      setAvailability({ state: "idle" });
      return;
    }
    setAvailability({ state: "checking" });
    let ignore = false;
    const timer = setTimeout(() => {
      checkUsernameAvailable({ username: candidate })
        .then((data) => {
          if (ignore) return;
          setAvailability(
            data.available
              ? {
                  state: "available",
                  discriminator: data.discriminator ?? null,
                  offer: data.offer ?? null,
                }
              : { state: "taken", reason: data.reason ?? "USERNAME_UNAVAILABLE" }
          );
        })
        .catch(() => {
          if (!ignore) setAvailability({ state: "idle" });
        });
    }, 350);
    return () => {
      ignore = true;
      clearTimeout(timer);
    };
  }, [value]);

  useEffect(() => {
    onChecked?.({
      usable: availability.state !== "checking" && availability.state !== "taken",
      offer: availability.state === "available" ? availability.offer : null,
    });
  }, [availability, onChecked]);

  const number =
    availability.state === "available" && availability.discriminator !== null
      ? String(availability.discriminator).padStart(4, "0")
      : null;

  return (
    <Field
      label={t("register.usernameLabel")}
      error={
        availability.state === "taken" &&
        tErrors(availability.reason, { defaultValue: tErrors("USERNAME_UNAVAILABLE") })
      }
      id={id}
    >
      <div className="relative">
        <Input
          value={value}
          onChange={(event) => {
            setTouched(true);
            onChange(event.target.value.toLowerCase());
          }}
          autoCapitalize="none"
          autoComplete="username"
          disabled={disabled}
          required
          className="pr-24"
          aria-describedby={`${id}-number`}
        />
        <span
          id={`${id}-number`}
          title={t("register.numberLocked")}
          className="pointer-events-none absolute inset-y-1 right-1 flex select-none items-center gap-1 rounded-sm bg-muted px-2 font-mono text-muted-foreground text-sm"
        >
          <Lock className="h-3 w-3" aria-hidden="true" />
          <span aria-hidden="true">#{number ?? "····"}</span>
          <span className="sr-only">
            {number ? t("register.numberLockedWith", { number }) : t("register.numberLocked")}
          </span>
        </span>
      </div>
    </Field>
  );
};
