/**
 * A list layout's presets: filters, and for a table a sort, that a person
 * picks to start from. Picking one makes them that person's own; the preset
 * itself stays as the layout keeps it. Each tool's presets hold the filters
 * its list narrows by, and it ships its own.
 */

import type { SortingState } from "@tanstack/react-table";

import type { SortField } from "@/api/generated/initiativeAPI.schemas";
import { collator } from "@/ui/lib/intl";
import { localized } from "@/ui/lib/localized";
import { slugify } from "@/ui/lib/slug";

import { type FieldDef, plainValue } from "./fields";
import type { StoredPreset } from "./layoutSet";

/** A preset as a list offers it, holding its tool's filters `F`. A shipped
 *  one is named by `nameKey`, in the reader's words, or, a tool plug-in's, in
 *  each language it ships (`names`). */
export type Preset<F> = {
  slug: string;
  name: string;
  nameKey?: string;
  names?: Readonly<Record<string, string>>;
  filters: F;
  sorting: SortingState;
};

/** A shipped preset: its slug, its name as a key in its tool's words, and its
 *  filters as kept. */
type ShippedPreset = { slug: string; nameKey: string; filters: Record<string, unknown> };

/** One tool's presets: the ones it ships, its filters read from what a
 *  layout keeps, and, where a preset can sort its list, that sort as the
 *  list's table names it, read from what a layout keeps and back. */
export type PresetKind<F> = {
  shipped: readonly ShippedPreset[];
  read: (raw: Record<string, unknown> | undefined) => F;
  sorting?: {
    read: (sort: SortField[]) => SortingState;
    stored: (sorting: SortingState) => SortField[];
  };
};

/** How many presets a list may offer, as the server allows. */
export const MAX_PRESETS = 20;

/** The presets a list offers: its own, or its tool's shipped ones where it
 *  keeps none of its own. One kept with no name is a shipped one no one
 *  renamed, named in each reader's words. */
export const presetsOf = <F>(
  definition: { presets?: readonly StoredPreset[] | null } | undefined,
  kind: PresetKind<F>
): Preset<F>[] =>
  definition?.presets == null
    ? kind.shipped.map(({ slug, nameKey, filters }) => ({
        slug,
        name: "",
        nameKey,
        filters: kind.read(filters),
        sorting: [],
      }))
    : definition.presets.map((preset) => {
        const names = typeof preset.name === "object" ? (preset.name ?? undefined) : undefined;
        const name = typeof preset.name === "string" ? preset.name : undefined;
        return {
          slug: preset.slug,
          name: name ?? preset.slug,
          names,
          nameKey:
            name || names
              ? undefined
              : kind.shipped.find((shipped) => shipped.slug === preset.slug)?.nameKey,
          filters: kind.read(preset.filters as Record<string, unknown> | undefined),
          sorting: kind.sorting?.read(preset.sort ?? []) ?? [],
        };
      });

/** A preset's name, in the reader's words or `language` where it is
 *  shipped. */
export const presetName = (
  preset: Pick<Preset<unknown>, "name" | "nameKey" | "names">,
  t: (key: string) => string,
  language = "en"
): string =>
  preset.nameKey
    ? t(preset.nameKey)
    : ((preset.names && localized(preset.names, language)) ?? preset.name);

/** `preset` of `kind` as a layout keeps it: a shipped one by its slug alone
 *  (a tool plug-in's by its names), so each reader still reads its name in
 *  their own words. */
export const storedPreset = <F>(preset: Preset<F>, kind: PresetKind<F>): StoredPreset => ({
  ...(preset.nameKey ? {} : { name: preset.names ?? preset.name }),
  slug: preset.slug,
  filters: preset.filters as StoredPreset["filters"],
  sort: kind.sorting?.stored(preset.sorting) ?? [],
});

/** A tool plug-in's presets' sort, by its table's fields: a column of its
 *  table is named for the field it shows. */
export const fieldSorting: NonNullable<PresetKind<unknown>["sorting"]> = {
  read: (sort) => sort.map(({ field, dir }) => ({ id: field, desc: dir === "desc" })),
  stored: (sorting) => sorting.map(({ id, desc }) => ({ field: id, dir: desc ? "desc" : "asc" })),
};

/** `items` in the order `sorting` puts them by `fields`' values, a new list:
 *  sorting is a view, and never the items' own order, which stays where two
 *  are alike. An empty value sorts last whichever way. */
export const sortedItems = <I>(
  items: readonly I[],
  sorting: SortingState,
  fields: ReadonlyMap<string, FieldDef<I>>,
  language?: string
): I[] => {
  const by = sorting.flatMap(({ id, desc }) => {
    const field = fields.get(id);
    return field ? [{ field, sign: desc ? -1 : 1 }] : [];
  });
  if (by.length === 0) return [...items];
  const words = collator(language, { numeric: true });
  const compare = (a: unknown, b: unknown): number =>
    typeof a === "string" && typeof b === "string" ? words.compare(a, b) : Number(a) - Number(b);
  return [...items].sort((left, right) => {
    for (const { field, sign } of by) {
      const a = plainValue(field.value(left));
      const b = plainValue(field.value(right));
      if (a == null || b == null) {
        if (a != null || b != null) return a == null ? 1 : -1;
        continue;
      }
      const order = compare(a, b);
      if (order !== 0) return order * sign;
    }
    return 0;
  });
};

const MAX_SLUG_LENGTH = 64;

/** A slug for a new preset named `name`, none of `taken`: what a link to it
 *  carries, so it stays when the preset is renamed. */
export const presetSlug = (name: string, taken: readonly string[]): string => {
  const base =
    slugify(name)
      .replaceAll("_", "-")
      .split("-")
      .filter(Boolean)
      .join("-")
      .slice(0, MAX_SLUG_LENGTH - 4)
      .replace(/-$/, "") || "preset";
  let slug = base;
  for (let n = 2; taken.includes(slug); n += 1) slug = `${base}-${n}`;
  return slug;
};
