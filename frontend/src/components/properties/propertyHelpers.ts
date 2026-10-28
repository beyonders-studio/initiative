import {
  type ListLayoutDefinitionInputDisplays,
  MetadataType,
  type PropertyDefinitionRead,
  type PropertyOption,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import type { MemberLike } from "@/components/members/MemberSearchSelect";

/**
 * Slugify a user-entered label into a stable option value slug. Output is
 * lowercase, alphanumeric plus `_` and `-`, trimmed of leading/trailing
 * underscores, and capped at 64 chars. Used both when creating a whole
 * definition (AddPropertyButton) and when appending a single option inline
 * (PropertyInput).
 */
export const slugify = (raw: string): string =>
  raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);

/** How a scale is drawn: a number, five stars, or a bar. */
export type ScaleDisplay = NonNullable<ListLayoutDefinitionInputDisplays>[string];

/** How each way of drawing a scale is offered, in order. */
export const SCALE_DISPLAYS: ScaleDisplay[] = ["number", "stars", "bar"];

/** The figure a scale holds, from 0 to 100, or null where it holds none. A
 *  plug-in's may carry a state beside it, as `{value, state}`. */
export const scaleValue = (raw: unknown): number | null => {
  const figure =
    raw !== null && typeof raw === "object" && "value" in raw
      ? (raw as { value: unknown }).value
      : raw;
  const value = numericValue(figure);
  return value === null ? null : Math.min(100, Math.max(0, value));
};

/** The amount a money or number value holds, or null where it holds none. */
export const numericValue = (raw: unknown): number | null => {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  if (typeof raw === "string" && raw.trim() !== "") {
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

export const typeRequiresOptions = (type: MetadataType): boolean =>
  type === MetadataType.select || type === MetadataType.multi_select;

export const isEmptyPropertyValue = (value: unknown): boolean => {
  if (value === null || value === undefined) return true;
  if (typeof value === "string" && value.trim() === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  return false;
};

/**
 * Build a fresh, unique option slug for a label that's about to be appended
 * to a definition's options array. If the straight-slugified value is already
 * in use, append ``-2``, ``-3``, … until we find a free slot. The caller is
 * expected to have already rejected duplicate labels (case-insensitive).
 */
export const buildUniqueOptionSlug = (label: string, existing: PropertyOption[]): string => {
  const base = slugify(label) || "option";
  const used = new Set(existing.map((o) => o.value));
  if (!used.has(base)) return base;
  for (let i = 2; i < 1000; i += 1) {
    const candidate = `${base}-${i}`;
    if (!used.has(candidate)) return candidate;
  }
  // Extremely unlikely; fall back to a timestamp suffix.
  return `${base}-${Date.now()}`;
};

/**
 * Normalize a draft option list for submission. The editor UI only collects a
 * label per option; the stored ``value`` slug is derived here. An option that
 * already carries a value (i.e. loaded from an existing definition) keeps it
 * verbatim so persisted task/file values stay attached; a freshly added
 * option derives its value from the label. Colliding slugs are disambiguated
 * with a numeric suffix, blank rows are dropped.
 */
export const normalizeOptionList = (options: PropertyOption[]): PropertyOption[] => {
  const result: PropertyOption[] = [];
  const used = new Set<string>();
  for (const option of options) {
    const label = option.label.trim() || option.value.trim();
    if (!label) continue;
    let value = option.value.trim() || slugify(label);
    if (!value) continue;
    if (used.has(value)) {
      let i = 2;
      while (used.has(`${value}-${i}`)) i += 1;
      value = `${value}-${i}`;
    }
    used.add(value);
    result.push({ value, label, color: option.color ?? null });
  }
  return result;
};

export const findOptionByLabel = (
  definition: PropertyDefinitionRead,
  label: string
): PropertyOption | undefined => {
  const needle = label.trim().toLowerCase();
  if (!needle) return undefined;
  return (definition.options ?? []).find((option) => option.label.trim().toLowerCase() === needle);
};

/**
 * The values an item's own properties list: its initiative's properties and,
 * on a task, its project's metadata. A collection's metadata is the
 * collection's to show and change, and a plug-in's values are drawn as its
 * fields.
 */
export const ownProperties = (summaries: PropertySummary[]): PropertySummary[] =>
  summaries.filter((summary) => summary.install_id === null && summary.collection_id === null);

/**
 * Extract the item's own values ({@link ownProperties}) that hold something,
 * in the same order they were returned by the server. Used by card chip rows
 * so empty rows are omitted.
 */
export const nonEmptyPropertySummaries = (
  summaries: PropertySummary[] | undefined | null
): PropertySummary[] => {
  if (!summaries) return [];
  return ownProperties(summaries).filter((summary) => !isEmptyPropertyValue(summary.value));
};

/** The person a ``user_reference`` value carries (the server reads it back as
 *  ``{id, display_name, …}``), so a picker can render them without a search. */
export const userReferenceValue = (property: PropertySummary): MemberLike | null => {
  if (property.type !== MetadataType.user_reference) return null;
  const raw = property.value;
  if (raw && typeof raw === "object" && typeof (raw as { id?: unknown }).id === "number") {
    return raw as MemberLike;
  }
  return null;
};

/** Convert a server ``PropertySummary.value`` into the shape an edited value
 *  takes: ``user_reference`` collapses to its numeric id (``PropertyInput``
 *  round-trips the id), everything else passes through. */
export const normalizePropertyValue = (property: PropertySummary): unknown =>
  property.type === MetadataType.user_reference
    ? (userReferenceValue(property)?.id ?? null)
    : (property.value ?? null);

/** A property just picked, before it has a value, as an item lists it. */
export const propertyStubFromDefinition = (
  definition: PropertyDefinitionRead
): PropertySummary => ({
  property_id: definition.id,
  name: definition.name,
  type: definition.type,
  project_id: definition.project_id,
  collection_id: definition.collection_id,
  install_id: null,
  key: null,
  options: definition.options ?? null,
  currency: definition.currency ?? null,
  value: null,
});
