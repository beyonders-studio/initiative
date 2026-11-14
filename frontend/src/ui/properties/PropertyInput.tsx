import { ChevronDown, Minus, Plus, RotateCcw, Star, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MetadataType,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { Combobox } from "@/ui/combobox";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Input } from "@/ui/input";
import { toPickerValue } from "@/ui/lib/localDateTime";
import { cn } from "@/ui/lib/utils";
import { type Member, type MemberId, MemberPicker, type SearchMembers } from "@/ui/member-picker";
import { Slider } from "@/ui/slider";

import { type FileFieldFiles, FileFieldInput } from "./FileFieldInput";
import { extractUser } from "./PropertyValueCell";
import {
  counterCount,
  counterSettings,
  type FieldDisplay,
  fileFieldValue,
  numericValue,
  type PropertyDefinition,
  scaleValue,
  steppedCount,
  withinBounds,
} from "./propertyHelpers";
import { SignatureFieldInput } from "./SignatureFieldInput";

type PropertyDefinitionLike = PropertyDefinition | PropertySummary;

export interface PropertyInputProps {
  definition: PropertyDefinitionLike;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  className?: string;
  /** Initiative that scopes the `user_reference` and `file` pickers. Falls back to the
   *  definition's own `initiative_id` when it carries one (an
   *  initiative's definition); required via this prop when the definition
   *  arrives as an embedded `PropertySummary`. */
  initiativeId?: number | null;
  /** The row whose readers a `user_reference` value may name (the task's
   *  project, the event's calendar, the file). Without it the picker
   *  offers the initiative's members, which is what a filter wants. */
  canOpen?: { tool: string; id: number | null | undefined };
  /** Adds an option named `label` to a select property, or finds the one
   *  already named so, and answers with it. A failure is told by this, and
   *  rejects. */
  appendOption: (
    definition: { id: number; options: PropertyOption[] },
    label: string
  ) => Promise<PropertyOption>;
  /** Finds the people a `user_reference` value may name. */
  searchMembers: SearchMembers<MemberId, string>;
  /** Who a pre-set `user_reference` value names, so the picker shows them
   *  without a search round-trip. Without it, the value is looked up. */
  selectedUser?: Member<MemberId> | null;
  /** How a scale is set: as a number, by stars, or along a bar. A number
   *  without. */
  display?: FieldDisplay | null;
  /** Steps a counter from what it holds when the step lands, so two people
   *  stepping it at once both count. Without it, a step is a value like any
   *  other: something nothing has saved yet, a filter. */
  onStep?: (up: boolean) => void;
  /** What a `file` value is picked from, linked to and drawn with. A file
   *  field draws nothing without it. */
  files?: FileFieldFiles;
  /** When the item last changed, on its own page, which a signature made
   *  before it says. */
  updatedAt?: string | null;
}

// ── Type guards / coercion helpers ──────────────────────────────────────────

const coerceString = (value: unknown): string => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
};

const coerceNumber = (value: unknown): string => {
  if (value == null || value === "") return "";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? String(parsed) : "";
  }
  return "";
};

const coerceBoolean = (value: unknown): boolean => value === true;

const coerceStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value.filter((v): v is string => typeof v === "string");
  }
  return [];
};

const coerceId = (value: unknown): number | null => {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "object" && value !== null && "id" in value) {
    const id = (value as { id: unknown }).id;
    if (typeof id === "number" && Number.isFinite(id)) return id;
  }
  return null;
};

/** A scale of 0–100 set as its layout draws it: a number, one of five stars
 *  (each a fifth), or a point along a bar. */
const ScaleInput = ({
  name,
  value,
  onChange,
  display,
  disabled,
  className,
}: {
  name: string;
  value: number | null;
  onChange: (value: unknown) => void;
  display: FieldDisplay;
  disabled: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("properties");
  if (display === "stars") {
    const filled = value === null ? 0 : Math.ceil(value / 20);
    return (
      <fieldset aria-label={name} className={cn("flex h-9 min-w-0 items-center", className)}>
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            aria-pressed={star === filled}
            aria-label={t("input.stars", { count: star })}
            disabled={disabled}
            className="rounded-sm p-0.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed"
            onClick={() => onChange(star * 20)}
          >
            <Star
              aria-hidden
              className={cn(
                "h-4 w-4",
                star <= filled ? "fill-current text-warning" : "text-muted-foreground/40"
              )}
            />
          </button>
        ))}
      </fieldset>
    );
  }
  if (display === "bar") {
    return (
      <div className={cn("flex h-9 items-center", className)}>
        <Slider
          min={0}
          max={100}
          step={1}
          value={[value ?? 0]}
          onValueChange={([next]) => onChange(next)}
          disabled={disabled}
          thumbLabel={name}
        />
      </div>
    );
  }
  // A whole number from 0 to 100; anything outside is brought within.
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Input
        type="number"
        inputMode="numeric"
        min={0}
        max={100}
        step={1}
        value={value === null ? "" : String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          const parsed = Math.round(Number(raw));
          onChange(
            raw === "" || !Number.isFinite(parsed) ? null : Math.min(100, Math.max(0, parsed))
          );
        }}
        placeholder={t("input.scalePlaceholder")}
        disabled={disabled}
        className="bg-transparent"
      />
      <span className="shrink-0 text-muted-foreground text-sm">%</span>
    </div>
  );
};

/** A counter: stepped down and up by its step, typed, or reset to its
 *  initial value, never past its bounds. */
const CounterInput = ({
  definition,
  value,
  onChange,
  onStep,
  disabled,
  className,
}: {
  definition: PropertyDefinitionLike;
  value: unknown;
  onChange: (value: unknown) => void;
  onStep?: (up: boolean) => void;
  disabled: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("properties");
  const settings = counterSettings(definition.counter);
  const count = counterCount(settings, value);
  const step = (up: boolean) => (onStep ? onStep(up) : onChange(steppedCount(settings, value, up)));
  return (
    <div className={cn("flex items-center gap-1", className)}>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label={t("input.stepDown", { name: definition.name })}
        disabled={disabled || (settings.min !== null && count <= settings.min)}
        onClick={() => step(false)}
      >
        <Minus className="h-4 w-4" />
      </Button>
      <Input
        type="number"
        inputMode="decimal"
        step="any"
        aria-label={definition.name}
        value={coerceNumber(value)}
        // As typed: the bounds hold it once it is saved, not a digit at a time.
        onChange={(e) => onChange(numericValue(e.target.value))}
        placeholder={String(settings.initial)}
        disabled={disabled}
        className="w-24 bg-transparent text-center tabular-nums"
      />
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label={t("input.stepUp", { name: definition.name })}
        disabled={disabled || (settings.max !== null && count >= settings.max)}
        onClick={() => step(true)}
      >
        <Plus className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="text-muted-foreground"
        aria-label={t("input.reset", { name: definition.name })}
        disabled={disabled || count === withinBounds(settings, settings.initial)}
        onClick={() => onChange(withinBounds(settings, settings.initial))}
      >
        <RotateCcw className="h-4 w-4" />
      </Button>
    </div>
  );
};

// ── Component ──────────────────────────────────────────────────────────────

export const PropertyInput = ({
  definition,
  value,
  onChange,
  disabled = false,
  className,
  initiativeId,
  canOpen,
  appendOption,
  searchMembers,
  selectedUser,
  display,
  onStep,
  files,
  updatedAt,
}: PropertyInputProps) => {
  const { t } = useTranslation("properties");

  const options = useMemo<PropertyOption[]>(
    () => (definition.options ?? []) as PropertyOption[],
    [definition.options]
  );

  switch (definition.type) {
    case MetadataType.text: {
      return (
        <Input
          type="text"
          value={coerceString(value)}
          onChange={(e) => {
            const next = e.target.value;
            onChange(next === "" ? null : next);
          }}
          placeholder={t("input.textPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case MetadataType.number: {
      return (
        <Input
          type="number"
          inputMode="numeric"
          value={coerceNumber(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(null);
              return;
            }
            const parsed = Number(raw);
            onChange(Number.isFinite(parsed) ? parsed : null);
          }}
          placeholder={t("input.numberPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case MetadataType.currency: {
      // An amount, in the currency the property names, beside it.
      return (
        <div className={cn("flex items-center gap-2", className)}>
          <Input
            type="number"
            inputMode="decimal"
            step="any"
            value={coerceNumber(value)}
            onChange={(e) => {
              const raw = e.target.value;
              const parsed = Number(raw);
              onChange(raw === "" || !Number.isFinite(parsed) ? null : parsed);
            }}
            placeholder={t("input.numberPlaceholder")}
            disabled={disabled}
            className="bg-transparent"
          />
          {definition.currency ? (
            <span className="shrink-0 text-muted-foreground text-sm">{definition.currency}</span>
          ) : null}
        </div>
      );
    }

    case MetadataType.scale: {
      return (
        <ScaleInput
          name={definition.name}
          value={scaleValue(value)}
          onChange={onChange}
          display={display ?? "number"}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.counter: {
      return (
        <CounterInput
          definition={definition}
          value={value}
          onChange={onChange}
          onStep={onStep}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.checkbox: {
      return (
        <div className={cn("flex h-9 items-center", className)}>
          <Checkbox
            checked={coerceBoolean(value)}
            onCheckedChange={(checked) => onChange(checked === true)}
            disabled={disabled}
          />
        </div>
      );
    }

    case MetadataType.url: {
      return (
        <Input
          type="url"
          value={coerceString(value)}
          onChange={(e) => {
            const next = e.target.value;
            onChange(next === "" ? null : next);
          }}
          placeholder={t("input.urlPlaceholder")}
          disabled={disabled}
          className={cn("bg-transparent", className)}
        />
      );
    }

    case MetadataType.date: {
      const stored = coerceString(value);
      return (
        <DateTimePicker
          value={stored}
          includeTime={false}
          onChange={(next) => onChange(next === "" ? null : next)}
          disabled={disabled}
          clearLabel={t("input.clear")}
        />
      );
    }

    case MetadataType.datetime: {
      // DateTimePicker stores `yyyy-MM-dd'T'HH:mm` as a local-time string.
      // Convert to a fully-qualified ISO string (with TZ offset) on write so
      // the backend stores an unambiguous instant.
      const stored = coerceString(value);
      const localValue = stored ? toPickerValue(stored) : "";
      return (
        <DateTimePicker
          value={localValue}
          includeTime
          onChange={(next) => {
            if (!next) {
              onChange(null);
              return;
            }
            const date = new Date(next);
            if (Number.isNaN(date.getTime())) {
              onChange(null);
              return;
            }
            onChange(date.toISOString());
          }}
          disabled={disabled}
          clearLabel={t("input.clear")}
        />
      );
    }

    case MetadataType.select: {
      return (
        <PropertyOptionPicker
          definition={definition}
          options={options}
          appendOption={appendOption}
          mode="single"
          selected={coerceString(value)}
          onChangeSingle={(next) => onChange(next ?? null)}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.multi_select: {
      return (
        <PropertyOptionPicker
          definition={definition}
          options={options}
          appendOption={appendOption}
          mode="multi"
          selectedMulti={coerceStringArray(value)}
          onChangeMulti={(next) => onChange(next)}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.user_reference: {
      // The people who can open the row the value sits on; without that row
      // (a filter), the property's initiative. Prefer the explicit prop,
      // falling back to the definition's own initiative when it carries one.
      return (
        <MemberPicker
          searchMembers={searchMembers}
          scope={
            canOpen
              ? { type: "canOpen", ...canOpen }
              : {
                  type: "initiative",
                  initiativeId:
                    initiativeId ??
                    ("initiative_id" in definition ? definition.initiative_id : null),
                }
          }
          value={extractUser(value)?.id ?? null}
          selected={selectedUser}
          onChange={(id) => onChange(id)}
          placeholder={t("input.userPlaceholder")}
          emptyMessage={t("input.textPlaceholder")}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.file: {
      return files ? (
        <FileFieldInput
          value={coerceId(value)}
          shown={"value" in definition ? fileFieldValue(definition.value) : null}
          onChange={onChange}
          files={files}
          disabled={disabled}
        />
      ) : null;
    }

    case MetadataType.signature: {
      return (
        <SignatureFieldInput
          name={definition.name}
          value={value}
          onChange={onChange}
          updatedAt={updatedAt}
          disabled={disabled}
        />
      );
    }

    default: {
      // Exhaustiveness check — fall back to a read-only rendering.
      return (
        <span className="text-muted-foreground text-sm">
          {String(value ?? t("input.textPlaceholder"))}
        </span>
      );
    }
  }
};

// ── Inline-creating option picker ───────────────────────────────────────────

type PropertyOptionPickerProps = {
  definition: PropertyDefinitionLike;
  options: PropertyOption[];
  appendOption: PropertyInputProps["appendOption"];
  disabled?: boolean;
  className?: string;
} & (
  | {
      mode: "single";
      selected: string;
      onChangeSingle: (next: string | null) => void;
      selectedMulti?: never;
      onChangeMulti?: never;
    }
  | {
      mode: "multi";
      selectedMulti: string[];
      onChangeMulti: (next: string[]) => void;
      selected?: never;
      onChangeSingle?: never;
    }
);

const PropertyOptionPicker = ({
  definition,
  options,
  appendOption,
  mode,
  selected,
  onChangeSingle,
  selectedMulti,
  onChangeMulti,
  disabled,
  className,
}: PropertyOptionPickerProps) => {
  const { t } = useTranslation("properties");
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);

  const isMulti = mode === "multi";
  const selectedArr = isMulti ? (selectedMulti ?? []) : selected ? [selected] : [];

  const knownValues = useMemo(() => new Set(options.map((option) => option.value)), [options]);

  // A failure rejects, so the picker keeps the typed name to try again.
  const handleCreate = async (label: string) => {
    if (adding) return;
    setAdding(true);
    try {
      const id = "id" in definition ? definition.id : definition.property_id;
      const slug = (await appendOption({ id, options }, label)).value;
      if (isMulti) {
        if (!selectedArr.includes(slug)) onChangeMulti([...selectedArr, slug]);
      } else {
        onChangeSingle(slug);
        setOpen(false);
      }
    } finally {
      setAdding(false);
    }
  };

  const selectedOptions = selectedArr
    .map(
      (slug) =>
        options.find((option) => option.value === slug) ?? { value: slug, label: slug, color: null }
    )
    .map((option) => ({
      ...option,
      known: knownValues.has(option.value),
    }));

  const placeholder = isMulti ? t("input.multiSelectPlaceholder") : t("input.selectPlaceholder");

  const shared = {
    items: options.map((option) => ({
      value: option.value,
      label: option.label,
      icon: option.color ? (
        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: option.color }} />
      ) : undefined,
    })),
    open,
    onOpenChange: setOpen,
    typedLabel: (typed: string) => typed && t("input.createOption", { label: typed }),
    onCreate: handleCreate,
    loading: adding,
    searchPlaceholder: t("input.searchOptions"),
    emptyMessage: t("picker.empty"),
    disabled,
    trigger: (
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        className={cn(
          "h-9 w-full justify-between bg-transparent font-normal",
          selectedOptions.length === 0 && "text-muted-foreground",
          className
        )}
      >
        {selectedOptions.length === 0 ? (
          <span className="truncate">{placeholder}</span>
        ) : (
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1 overflow-hidden">
            {selectedOptions.map((option) => (
              <span
                key={option.value}
                className={cn(
                  "inline-flex max-w-full items-center gap-1 truncate rounded-sm px-1.5 py-0.5 text-xs",
                  option.known
                    ? "bg-muted text-foreground"
                    : "bg-muted text-muted-foreground italic"
                )}
              >
                {option.color ? (
                  <span
                    className="inline-block h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: option.color }}
                  />
                ) : null}
                <span className="truncate">
                  {option.known ? option.label : t("input.unknownOption", { value: option.value })}
                </span>
                {isMulti ? (
                  // A <button> can't sit inside the trigger's own button, so a span
                  // takes the button's role.
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={t("input.clear")}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                    onClick={(e) => {
                      e.stopPropagation();
                      onChangeMulti(selectedArr.filter((v) => v !== option.value));
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        onChangeMulti(selectedArr.filter((v) => v !== option.value));
                      }
                    }}
                  >
                    <X className="h-3 w-3" />
                  </span>
                ) : null}
              </span>
            ))}
          </span>
        )}
        <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
      </Button>
    ),
  };

  return isMulti ? (
    <Combobox {...shared} multiple value={selectedArr} onValueChange={onChangeMulti} />
  ) : (
    // Choosing the chosen option again clears it.
    <Combobox
      {...shared}
      value={selected || null}
      onValueChange={(next) => onChangeSingle(next === selected ? null : next)}
    />
  );
};

// ── Helpers ─────────────────────────────────────────────────────────────────
