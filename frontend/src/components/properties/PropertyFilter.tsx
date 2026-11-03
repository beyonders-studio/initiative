import { Plus, X } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { MetadataType } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { type MetadataOwner, useOwnedDefinitions } from "@/hooks/useProperties";
import { cn } from "@/lib/utils";

import { PropertyInput, type PropertyInputProps } from "./PropertyInput";
import { iconForPropertyType } from "./propertyTypeIcons";

export interface PropertyFilterCondition {
  property_id: number;
  op: string;
  value: unknown;
}

/** A filter on a plug-in's field, by its id (`plugin:<install>:<key>`). */
export interface PluginFilterCondition {
  field: string;
  op: string;
  value: unknown;
}

/** A plug-in field a list may be filtered by, as the type it compares like. */
export interface PluginFilterField {
  id: string;
  name: string;
  type: MetadataType;
}

export interface PropertyFilterProps {
  value: PropertyFilterCondition[];
  /** Called with the property filters, and the plug-in fields' filters. */
  onChange: (next: PropertyFilterCondition[], plugins: PluginFilterCondition[]) => void;
  /** Plug-in fields offered beside the properties, and the filters on them. */
  plugins?: { fields: PluginFilterField[]; value: PluginFilterCondition[] };
  /**
   * Initiative to scope the definitions to. Omit on global views
   * (union across every initiative the caller can see).
   */
  initiativeId?: number;
  /** The project whose metadata is offered beside the properties: a
   *  project's own task list. */
  owner?: MetadataOwner;
  maxFilters?: number;
  className?: string;
}

/**
 * Supported filter operators, keyed by the backend :class:`FilterOp` enum.
 *
 * Backend reference: `backend/app/schemas/query.py` ``FilterOp``. We ship a
 * small subset tailored to each property type. ``ilike`` is labeled
 * "contains" in the UI because the backend wraps the value in ``%value%``.
 * ``multi_select`` always uses JSONB containment regardless of ``op``; we
 * keep ``eq`` in the dropdown as a single sensible default for that type.
 */
const BACKEND_OPS = ["eq", "lt", "lte", "gt", "gte", "in_", "ilike", "is_null"] as const;
type BackendOp = (typeof BACKEND_OPS)[number];

const DEFAULT_MAX_FILTERS = 5;

/**
 * Return the ordered list of operators that make sense for a property type.
 * The first entry is used as the default when adding a new filter.
 */
export const opsForType = (type: MetadataType): BackendOp[] => {
  switch (type) {
    case MetadataType.text:
    case MetadataType.url:
      return ["ilike", "eq", "is_null"];
    case MetadataType.number:
    case MetadataType.currency:
    case MetadataType.scale:
    case MetadataType.date:
    case MetadataType.datetime:
      return ["eq", "lt", "lte", "gt", "gte", "is_null"];
    case MetadataType.checkbox:
      return ["eq", "is_null"];
    case MetadataType.select:
      return ["eq", "in_", "is_null"];
    case MetadataType.multi_select:
      // Backend always uses JSONB ``@>`` for multi_select; we only need one row.
      return ["eq"];
    case MetadataType.user_reference:
      return ["eq", "in_", "is_null"];
    default:
      return ["eq"];
  }
};

const isBackendOp = (op: string): op is BackendOp =>
  (BACKEND_OPS as readonly string[]).includes(op);

/**
 * Translate a ``FilterOp`` to its short UI label. Keys are intentionally
 * flat (no nested object per type) so localizers only touch one map.
 */
const useOpLabel = () => {
  const { t } = useTranslation("properties");
  return useCallback((op: string) => t(`filter.ops.${op}` as never, { defaultValue: op }), [t]);
};

/**
 * Produce a sensible default value for a fresh row so the input component
 * renders in a defined state. The backend treats "empty" conditions as
 * no-ops, so we don't need to coerce here — the user just edits the value.
 */
const defaultValueForDefinition = (definition: { type: MetadataType }, op: BackendOp): unknown => {
  if (op === "is_null") {
    return true;
  }
  switch (definition.type) {
    case MetadataType.checkbox:
      return false;
    case MetadataType.multi_select:
      return [];
    case MetadataType.number:
      return null;
    default:
      return op === "in_" ? [] : null;
  }
};

/** One thing a filter row names: a property, or a plug-in's field. */
type FilterOption = {
  key: string;
  name: string;
  type: MetadataType;
  /** What the value is entered as. */
  input: PropertyInputProps["definition"];
  /** A plug-in's value compares as text or as a number, never as one of many. */
  plugin: boolean;
};

type FilterRow = { key: string; op: string; value: unknown };

const PROPERTY_KEY = "property:";

export const PropertyFilter = ({
  value,
  onChange,
  plugins,
  initiativeId,
  owner,
  maxFilters = DEFAULT_MAX_FILTERS,
  className,
}: PropertyFilterProps) => {
  const { t } = useTranslation("properties");
  const opLabel = useOpLabel();

  // Pull the definitions the caller can see (scoped when ``initiativeId`` is
  // provided, union across accessible initiatives otherwise). The hook
  // caches cross-page so we don't incur a request per component.
  const definitionsQuery = useOwnedDefinitions({ initiativeId, owner });

  const options = useMemo<FilterOption[]>(
    () => [
      ...(definitionsQuery.data ?? []).map((definition) => ({
        key: `${PROPERTY_KEY}${definition.id}`,
        name: definition.name,
        type: definition.type,
        input: definition,
        plugin: false,
      })),
      ...(plugins?.fields ?? []).map((field) => ({
        key: field.id,
        name: field.name,
        type: field.type,
        input: {
          property_id: 0,
          name: field.name,
          type: field.type,
          project_id: null,
          collection_id: null,
          install_id: null,
          key: null,
          options: null,
          currency: null,
          value: null,
        },
        plugin: true,
      })),
    ],
    [definitionsQuery.data, plugins?.fields]
  );

  const optionsByKey = useMemo(
    () => new Map(options.map((option) => [option.key, option])),
    [options]
  );

  const rows = useMemo<FilterRow[]>(
    () => [
      ...value.map(({ property_id, op, value: entry }) => ({
        key: `${PROPERTY_KEY}${property_id}`,
        op,
        value: entry,
      })),
      ...(plugins?.value ?? []).map(({ field, op, value: entry }) => ({
        key: field,
        op,
        value: entry,
      })),
    ],
    [value, plugins?.value]
  );

  const emit = useCallback(
    (next: FilterRow[]) =>
      onChange(
        next
          .filter((row) => row.key.startsWith(PROPERTY_KEY))
          .map(({ key, op, value: entry }) => ({
            property_id: Number(key.slice(PROPERTY_KEY.length)),
            op,
            value: entry,
          })),
        next
          .filter((row) => !row.key.startsWith(PROPERTY_KEY))
          .map(({ key, op, value: entry }) => ({ field: key, op, value: entry }))
      ),
    [onChange]
  );

  const opsFor = useCallback(
    (option: FilterOption) =>
      option.plugin
        ? opsForType(option.type).filter((op) => op !== "in_")
        : opsForType(option.type),
    []
  );

  const used = useMemo(() => new Set(rows.map((row) => row.key)), [rows]);

  const handleAddFilter = useCallback(() => {
    const firstAvailable = options.find((option) => !used.has(option.key));
    if (!firstAvailable) return;
    const op = opsFor(firstAvailable)[0] ?? "eq";
    emit([
      ...rows,
      { key: firstAvailable.key, op, value: defaultValueForDefinition(firstAvailable, op) },
    ]);
  }, [options, used, rows, emit, opsFor]);

  const handleRemoveFilter = useCallback(
    (index: number) => {
      emit(rows.filter((_, i) => i !== index));
    },
    [rows, emit]
  );

  const handlePropertyChange = useCallback(
    (index: number, nextKey: string) => {
      const next = optionsByKey.get(nextKey);
      if (!next) return;
      const op = opsFor(next)[0] ?? "eq";
      emit(
        rows.map((entry, i) =>
          i === index ? { key: next.key, op, value: defaultValueForDefinition(next, op) } : entry
        )
      );
    },
    [optionsByKey, rows, emit, opsFor]
  );

  const handleOpChange = useCallback(
    (index: number, nextOp: string) => {
      const entry = rows[index];
      if (!entry) return;
      const option = optionsByKey.get(entry.key);
      if (!option) return;
      const normalized = isBackendOp(nextOp) ? nextOp : "eq";
      // Reset value shape when switching between scalar / array / null ops so
      // the input component isn't stuck with a non-matching draft.
      const shouldResetValue =
        normalized === "in_" ||
        normalized === "is_null" ||
        entry.op === "in_" ||
        entry.op === "is_null";
      const nextValue = shouldResetValue
        ? defaultValueForDefinition(option, normalized)
        : entry.value;
      emit(
        rows.map((existing, i) =>
          i === index ? { ...existing, op: normalized, value: nextValue } : existing
        )
      );
    },
    [rows, emit, optionsByKey]
  );

  const handleValueChange = useCallback(
    (index: number, nextValue: unknown) => {
      emit(rows.map((entry, i) => (i === index ? { ...entry, value: nextValue } : entry)));
    },
    [rows, emit]
  );

  const canAddMore = rows.length < maxFilters && options.length > used.size;

  if (options.length === 0 && rows.length === 0) {
    // Nothing to filter on — don't take up UI real estate.
    return null;
  }

  return (
    <div className={cn("space-y-2", className)}>
      {rows.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {rows.map((entry, index) => {
            const definition = optionsByKey.get(entry.key);
            const ops = definition ? opsFor(definition) : ["eq"];
            return (
              <li key={entry.key} className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
                <div className="min-w-0 flex-1 sm:w-40 sm:flex-none">
                  <Select
                    value={entry.key}
                    onValueChange={(next) => handlePropertyChange(index, next)}
                  >
                    <SelectTrigger className="h-9 w-full" aria-label={t("filter.property")}>
                      {definition ? (
                        (() => {
                          const Icon = iconForPropertyType(definition.type);
                          return (
                            <div className="flex min-w-0 items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0" />
                              <span className="truncate">{definition.name}</span>
                            </div>
                          );
                        })()
                      ) : (
                        <SelectValue />
                      )}
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((option) => {
                        const Icon = iconForPropertyType(option.type);
                        return (
                          <SelectItem
                            key={option.key}
                            value={option.key}
                            textValue={option.name}
                            disabled={option.key !== entry.key && used.has(option.key)}
                          >
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 shrink-0" />
                              <span>{option.name}</span>
                            </div>
                          </SelectItem>
                        );
                      })}
                    </SelectContent>
                  </Select>
                </div>
                <div className="sm:w-32">
                  <Select
                    value={entry.op}
                    onValueChange={(next) => handleOpChange(index, next)}
                    disabled={!definition}
                  >
                    <SelectTrigger className="h-9 w-full" aria-label={t("filter.operator")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ops.map((opOption) => (
                        <SelectItem key={opOption} value={opOption}>
                          {opLabel(opOption)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="min-w-0 flex-1">
                  {definition && entry.op !== "is_null" ? (
                    <PropertyInput
                      definition={definition.input}
                      value={entry.value}
                      onChange={(next) => handleValueChange(index, next)}
                    />
                  ) : (
                    <div className="text-muted-foreground text-sm">{opLabel(entry.op)}</div>
                  )}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleRemoveFilter(index)}
                  aria-label={t("filter.remove")}
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      ) : null}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleAddFilter}
        disabled={!canAddMore}
        className="h-8"
      >
        <Plus className="h-4 w-4" />
        {t("filter.addFilter")}
      </Button>
    </div>
  );
};

/** A list's `property_filters` param, a JSON-encoded array, as conditions. */
export const parsePropertyFilters = (
  encoded: string | null | undefined
): PropertyFilterCondition[] => {
  if (!encoded) return [];
  try {
    const parsed: unknown = JSON.parse(encoded);
    return Array.isArray(parsed) ? (parsed as PropertyFilterCondition[]) : [];
  } catch {
    return [];
  }
};

export interface PropertyFilterParamProps {
  /** The list's `property_filters` param. */
  value: string | null | undefined;
  onChange: (next: string | undefined) => void;
  initiativeId?: number;
}

/** A {@link PropertyFilter} over a tool list's `property_filters` param. */
export const PropertyFilterParam = ({
  value,
  onChange,
  initiativeId,
}: PropertyFilterParamProps) => (
  <PropertyFilter
    value={parsePropertyFilters(value)}
    onChange={(next) => onChange(next.length > 0 ? JSON.stringify(next) : undefined)}
    initiativeId={initiativeId}
  />
);
