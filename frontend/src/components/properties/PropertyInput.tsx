import { Check, ChevronDown, Plus, Star, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MetadataType,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertySummary,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { type MemberLike, MemberSelect } from "@/components/members/MemberSearchSelect";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { useAppendPropertyOption } from "@/hooks/useProperties";
import { toPickerValue } from "@/lib/localDateTime";
import { cn } from "@/lib/utils";

import { type ScaleDisplay, scaleValue } from "./propertyHelpers";

type PropertyDefinitionLike = PropertyDefinitionRead | PropertySummary;

export interface PropertyInputProps {
  definition: PropertyDefinitionLike;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  className?: string;
  /** Initiative that scopes the `user_reference` picker. Falls back to the
   *  definition's own `initiative_id` when it carries one (a full
   *  `PropertyDefinitionRead`); required via this prop when the definition
   *  arrives as an embedded `PropertySummary`. */
  initiativeId?: number | null;
  /** The row whose readers a `user_reference` value may name (the task's
   *  project, the event's calendar, the file). Without it the picker
   *  offers the initiative's members, which is what a filter wants. */
  canOpen?: { tool: Tool; id: number | null | undefined };
  /** Display info for a pre-set `user_reference` value so the picker shows a
   *  name without a search round-trip (the server returns `{id, display_name}`
   *  on reads). */
  selectedUser?: MemberLike | null;
  /** How a scale is set: as a number, by stars, or along a bar. A number
   *  without. */
  display?: ScaleDisplay | null;
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

const coerceUserId = (value: unknown): number | null => {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "object" && value !== null && "id" in value) {
    const id = (value as { id: unknown }).id;
    if (typeof id === "number" && Number.isFinite(id)) return id;
  }
  return null;
};

// Construct the (minimal) ``PropertyDefinitionRead`` shape the append-option
// hook expects. The local definition may arrive as a ``PropertySummary``
// embedded on an entity read; those have the same ``options`` + id fields
// under different names.
const toDefinitionForPatch = (defn: PropertyDefinitionLike): PropertyDefinitionRead => {
  if ("id" in defn) return defn;
  const summary = defn as PropertySummary;
  return {
    id: summary.property_id,
    // The remaining fields aren't used by the append helper, but the type
    // demands them. They're harmless placeholders.
    initiative_id: 0,
    name: summary.name,
    type: summary.type,
    position: 0,
    color: null,
    options: summary.options ?? null,
    currency: summary.currency ?? null,
    project_id: summary.project_id,
    collection_id: summary.collection_id,
    created_at: "",
    updated_at: "",
  } as PropertyDefinitionRead;
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
  display: ScaleDisplay;
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

// ── Component ──────────────────────────────────────────────────────────────

export const PropertyInput = ({
  definition,
  value,
  onChange,
  disabled = false,
  className,
  initiativeId,
  canOpen,
  selectedUser,
  display,
}: PropertyInputProps) => {
  const { t } = useTranslation(["properties", "common"]);

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
          placeholder={t("properties:input.textPlaceholder")}
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
          placeholder={t("properties:input.numberPlaceholder")}
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
            placeholder={t("properties:input.numberPlaceholder")}
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
          placeholder={t("properties:input.urlPlaceholder")}
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
          clearLabel={t("properties:input.clear")}
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
          clearLabel={t("properties:input.clear")}
        />
      );
    }

    case MetadataType.select: {
      return (
        <PropertyOptionPicker
          definition={definition}
          options={options}
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
          mode="multi"
          selectedMulti={coerceStringArray(value)}
          onChangeMulti={(next) => onChange(next)}
          disabled={disabled}
          className={className}
        />
      );
    }

    case MetadataType.user_reference: {
      const currentId = coerceUserId(value);
      // The people who can open the row the value sits on; without that row
      // (a filter), the property's initiative. Prefer the explicit prop,
      // falling back to the definition's own initiative when it carries one.
      const scopedInitiativeId =
        initiativeId ?? ("initiative_id" in definition ? definition.initiative_id : null);
      return (
        <MemberSelect
          scope={
            canOpen
              ? { type: "canOpen", ...canOpen }
              : { type: "initiative", initiativeId: scopedInitiativeId }
          }
          value={currentId}
          onChange={(next) => onChange(next)}
          selectedUser={selectedUser ?? null}
          placeholder={t("properties:input.userPlaceholder")}
          emptyMessage={t("properties:input.textPlaceholder")}
          disabled={disabled}
          className={className}
        />
      );
    }

    default: {
      // Exhaustiveness check — fall back to a read-only rendering.
      return (
        <span className="text-muted-foreground text-sm">
          {String(value ?? t("properties:input.textPlaceholder"))}
        </span>
      );
    }
  }
};

// ── Inline-creating option picker ───────────────────────────────────────────

type PropertyOptionPickerProps = {
  definition: PropertyDefinitionLike;
  options: PropertyOption[];
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
  mode,
  selected,
  onChangeSingle,
  selectedMulti,
  onChangeMulti,
  disabled,
  className,
}: PropertyOptionPickerProps) => {
  const { t } = useTranslation(["properties", "common"]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { appendOption, isPending } = useAppendPropertyOption();

  const isMulti = mode === "multi";
  const selectedArr = isMulti ? (selectedMulti ?? []) : selected ? [selected] : [];

  const knownValues = useMemo(() => new Set(options.map((option) => option.value)), [options]);

  const filteredOptions = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((option) => option.label.toLowerCase().includes(needle));
  }, [options, search]);

  const exactLabelMatch = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return null;
    return options.find((option) => option.label.trim().toLowerCase() === needle) ?? null;
  }, [options, search]);

  const canCreate = search.trim().length > 0 && !exactLabelMatch && !disabled;

  const handleToggle = (value: string) => {
    if (isMulti) {
      const current = selectedMulti ?? [];
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      onChangeMulti(next);
      return;
    }
    if (selected === value) {
      onChangeSingle(null);
    } else {
      onChangeSingle(value);
      setOpen(false);
    }
  };

  const handleCreate = async () => {
    if (!search.trim()) return;
    try {
      const result = await appendOption(toDefinitionForPatch(definition), search);
      setSearch("");
      const slug = result.option.value;
      if (isMulti) {
        const current = selectedMulti ?? [];
        if (!current.includes(slug)) {
          onChangeMulti([...current, slug]);
        }
      } else {
        onChangeSingle(slug);
        setOpen(false);
      }
    } catch {
      // Toast surfaced by the hook.
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

  const placeholder = isMulti
    ? t("properties:input.multiSelectPlaceholder")
    : t("properties:input.selectPlaceholder");

  return (
    <Popover open={open} onOpenChange={(next) => (!disabled ? setOpen(next) : null)}>
      <PopoverTrigger asChild>
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
                    {option.known
                      ? option.label
                      : t("properties:input.unknownOption", { value: option.value })}
                  </span>
                  {isMulti ? (
                    // biome-ignore lint/a11y/useSemanticElements: can't nest a <button> inside the parent PopoverTrigger button; span+role is the workaround
                    <span
                      role="button"
                      tabIndex={0}
                      aria-label={t("properties:input.clear")}
                      className="shrink-0 text-muted-foreground hover:text-foreground"
                      onClick={(e) => {
                        e.stopPropagation();
                        onChangeMulti((selectedMulti ?? []).filter((v) => v !== option.value));
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          e.stopPropagation();
                          onChangeMulti((selectedMulti ?? []).filter((v) => v !== option.value));
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
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={t("properties:input.searchOptions")}
            value={search}
            onValueChange={setSearch}
            disabled={isPending}
          />
          <CommandList>
            {filteredOptions.length === 0 && !canCreate ? (
              <CommandEmpty>{t("properties:picker.empty")}</CommandEmpty>
            ) : null}
            {filteredOptions.length > 0 ? (
              <CommandGroup>
                {filteredOptions.map((option) => {
                  const isSelected = selectedArr.includes(option.value);
                  return (
                    <CommandItem
                      key={option.value}
                      value={option.value}
                      onSelect={() => handleToggle(option.value)}
                      className="flex items-center gap-2"
                    >
                      {option.color ? (
                        <span
                          className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: option.color }}
                        />
                      ) : null}
                      <span className="flex-1 truncate">{option.label}</span>
                      {isSelected ? <Check className="h-4 w-4 shrink-0" /> : null}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ) : null}
            {canCreate ? (
              <>
                {filteredOptions.length > 0 ? <CommandSeparator /> : null}
                <CommandGroup>
                  <CommandItem
                    value="__create__"
                    onSelect={handleCreate}
                    disabled={isPending}
                    className="flex items-center gap-2"
                  >
                    <Plus className="h-4 w-4 shrink-0" />
                    <span className="truncate">
                      {t("properties:input.createOption", { label: search.trim() })}
                    </span>
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

// ── Helpers ─────────────────────────────────────────────────────────────────
