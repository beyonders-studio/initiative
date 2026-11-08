/**
 * A list layout's presets: filters, and for a table a sort, that a person
 * picks to start from. Picking one makes them that person's own; the preset
 * itself stays as the layout keeps it. Each tool's presets hold the filters
 * its list narrows by, and it ships its own.
 */

import type { SortingState } from "@tanstack/react-table";

import type {
  LayoutPreset,
  ListLayoutDefinitionInput,
  PresetSortField,
  SortDir,
  SortField,
} from "@/api/generated/initiativeAPI.schemas";
import { slugify } from "@/ui/lib/slug";

/** A preset as a list offers it, holding its tool's filters `F`. A shipped
 *  one is named by `nameKey`, in the reader's words. */
export type Preset<F> = {
  slug: string;
  name: string;
  nameKey?: string;
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
  definition: ListLayoutDefinitionInput | undefined,
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
    : definition.presets.map((preset) => ({
        slug: preset.slug,
        name: preset.name ?? preset.slug,
        nameKey: preset.name
          ? undefined
          : kind.shipped.find((shipped) => shipped.slug === preset.slug)?.nameKey,
        filters: kind.read(preset.filters as Record<string, unknown> | undefined),
        sorting: kind.sorting?.read(preset.sort ?? []) ?? [],
      }));

/** A preset's name, in the reader's words where it is shipped. */
export const presetName = (
  preset: Pick<Preset<unknown>, "name" | "nameKey">,
  t: (key: string) => string
): string => (preset.nameKey ? t(preset.nameKey) : preset.name);

/** `preset` of `kind` as a layout keeps it: a shipped one by its slug alone,
 *  so each reader still reads its name in their own words. */
export const storedPreset = <F>(preset: Preset<F>, kind: PresetKind<F>): LayoutPreset => ({
  ...(preset.nameKey ? {} : { name: preset.name }),
  slug: preset.slug,
  filters: preset.filters as LayoutPreset["filters"],
  sort: (kind.sorting?.stored(preset.sorting) ?? []).map(({ field, dir }) => ({
    field: field as PresetSortField,
    dir: dir as SortDir,
  })),
});

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
