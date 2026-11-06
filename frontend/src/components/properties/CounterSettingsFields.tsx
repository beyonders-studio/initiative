import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CounterSettingsInput } from "@/api/generated/initiativeAPI.schemas";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { numericValue } from "./propertyHelpers";

const SETTINGS = ["step", "min", "max", "initial"] as const;
type Setting = (typeof SETTINGS)[number];

/** Why a counter's settings cannot be saved as they are, or null. */
const problemWith = ({ step, min, max }: CounterSettingsInput) => {
  if (step != null && step <= 0) return "stepPositive" as const;
  if (min != null && max != null && min > max) return "minAboveMax" as const;
  return null;
};

/** Whether a counter's settings can be saved as they are. */
export const counterSettingsValid = (settings: CounterSettingsInput): boolean =>
  problemWith(settings) === null;

/**
 * A counter's step, its bounds and the value a reset goes back to. A number
 * left empty is the default: a step of one, no bound, or zero.
 */
export const CounterSettingsFields = ({
  value,
  onChange,
  disabled = false,
}: {
  value: CounterSettingsInput;
  onChange: (settings: CounterSettingsInput) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("properties");
  const id = useId();
  // As typed, while it reads as the setting holds: a number being written
  // ("-", "1.") stays as it is, and a setting changed from outside shows.
  const [text, setText] = useState<Partial<Record<Setting, string>>>({});
  const shown = (setting: Setting) => {
    const typed = text[setting] ?? "";
    const held = value[setting] ?? null;
    return numericValue(typed) === held ? typed : held === null ? "" : String(held);
  };
  const change = (setting: Setting, typed: string) => {
    setText((prev) => ({ ...prev, [setting]: typed }));
    const number = numericValue(typed);
    onChange({
      ...value,
      [setting]: number ?? (setting === "min" || setting === "max" ? null : undefined),
    });
  };
  const problem = problemWith(value);
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-pair gap-2">
        {SETTINGS.map((setting) => (
          <div key={setting} className="space-y-1">
            <Label htmlFor={`${id}-${setting}`} className="font-normal text-xs">
              {t(`counter.${setting}`)}
            </Label>
            <Input
              id={`${id}-${setting}`}
              type="number"
              inputMode="decimal"
              step="any"
              value={shown(setting)}
              onChange={(e) => change(setting, e.target.value)}
              placeholder={t(`counter.${setting}Placeholder`)}
              disabled={disabled}
            />
          </div>
        ))}
      </div>
      {problem ? <p className="text-destructive text-xs">{t(`counter.${problem}`)}</p> : null}
    </div>
  );
};
