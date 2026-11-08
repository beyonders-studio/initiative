/**
 * How a list's items are grouped: by any field whose values group, as the
 * server's field registry names it, or a custom property. The server works out
 * the groups: which an item is in, and their order. What is left here is
 * drawing them, which is decided by the kind of field rather than by each
 * field, and what a drop from one group into another writes; the kind of item
 * says both for its own fields ({@link OwnGroups}). A table draws a grouping
 * as header rows, a board as bands across its columns.
 */

import type { GroupingState } from "@tanstack/react-table";
import type { ReactNode } from "react";

import {
  type DateBucket,
  type GroupingDescription,
  type GroupsResponse,
  type LayoutGrouping,
  type ListLayoutDefinitionOutput,
  type ListLayoutReadKind,
  MetadataType,
  type PropertyDefinitionRead,
  type PropertySummary,
  type PropertyValuesSetRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/ui/lib/intl";
import { extractUser, PropertyValueCell } from "@/ui/properties/PropertyValueCell";
import { propertyStubFromDefinition } from "@/ui/properties/propertyHelpers";

import type { FieldDef, LayoutEnv } from "./fields";

/** The key of the group an item with no value falls into. */
export const NO_GROUP = "";

/** What a drop from one group of a property into another writes. */
export type PropertyMove = { properties: PropertyValuesSetRequest };

/** A field a list can be grouped by, as what a layout offers is read from:
 *  one the field catalog offers, or a custom property whose values group. */
export type GroupingChoice = {
  /** What a layout names it by: the field's name, or `property:<id>`. */
  id: string;
  /** Whether it groups by a bucket of the calendar. */
  bucket: boolean;
  /** Whether it is what a board's columns are, so its bands never are. */
  columns?: boolean;
  property?: PropertyDefinitionRead;
};

/** A grouping choice, as a list draws it. */
export type Groupable = GroupingChoice & {
  label: string;
  /** The registry's kind of field, or `property`. */
  kind: string;
};

/** The fields the catalog says group, as choices, `columns` the one a
 *  board's columns are. */
export const catalogChoices = (
  catalog: GroupingDescription[],
  columns?: string
): GroupingChoice[] =>
  catalog.map((entry) => ({
    id: entry.name,
    bucket: entry.bucket ?? false,
    columns: entry.name === columns,
  }));

/** One way to split a list's items, as a list offers it. */
export type ItemGrouping<I, M> = {
  id: string;
  /** The table's hidden column for it, which is what a person's view keeps. */
  column: string;
  label: string;
  /** For a date, the bucket of the calendar it groups by. */
  bucket?: DateBucket | null;
  /** The groups an item is in: none puts it in {@link NO_GROUP}, several in each. */
  keys: (item: I) => string[];
  /** Every group there is, in order, whether or not an item is in it. */
  values?: string[];
  /** The order of two groups. */
  compare: (a: string, b: string) => number;
  header: (key: string) => ReactNode;
  /** The write a drop from `from` into `to` makes; left out where a drop
   *  can't change anything (a date window isn't a date). */
  move?: (from: string, to: string) => M;
};

/** A grouping a list offers, and the groups it leaves out while grouped by it. */
export type OfferedGrouping<I, M> = {
  grouping: ItemGrouping<I, M>;
  hidden: ReadonlySet<string>;
};

/** What a kind of item says of a grouping by one of its own fields. */
export type OwnGroups<M> = {
  /** How a group is drawn, by its key: words, drawn as a group's name is, or
   *  an element of its own; nothing where the name the server gave it, or the
   *  empty group's, says it. */
  header: (field: Groupable, key: string) => ReactNode;
  /** The write a drop from one group into another makes, where a drop can
   *  change the field. */
  move: (id: string) => ((from: string, to: string) => M) | undefined;
};

/** The groups the server worked out for one grouping. */
export type ServedGroups = { field: string; data: GroupsResponse };

/** A grouping's table column, as a person's view keeps it. */
export const groupColumn = (id: string) => `${id} group`;

/** The most groupings a layout offers, and groups one leaves out, as the
 *  server holds a layout to. */
export const MAX_GROUPINGS = 50;
export const MAX_HIDDEN_GROUPS = 200;

/** The buckets a date groups by. */
export const DATE_BUCKETS: DateBucket[] = ["day", "week", "month", "quarter", "year"];

const groupsBy = (kind: ListLayoutReadKind, all: GroupingChoice[], id: string) =>
  kind !== "board" || !all.some((each) => each.columns && each.id === id);

const GROUPING_PROPERTIES: ReadonlySet<string> = new Set([
  MetadataType.select,
  MetadataType.multi_select,
  MetadataType.user_reference,
  MetadataType.checkbox,
]);
const DATE_PROPERTIES: ReadonlySet<string> = new Set([MetadataType.date, MetadataType.datetime]);

/**
 * What a list's items can be grouped by: the fields the catalog says group,
 * `columns` the one a board's columns are, then the properties that do, in
 * the fields' order.
 */
export const groupables = (
  catalog: GroupingDescription[],
  fields: ReadonlyMap<string, FieldDef>,
  t: LayoutEnv["t"],
  columns?: string
): Groupable[] => [
  ...catalog.map((entry) => ({
    id: entry.name,
    bucket: entry.bucket ?? false,
    columns: entry.name === columns,
    kind: entry.kind,
    label: t(`layouts:groupings.fields.${entry.name}`, {
      defaultValue: t(`dashboards:filterField.${entry.name}`, {
        defaultValue: entry.name,
      }),
    }),
  })),
  ...[...fields.values()].flatMap((field): Groupable[] => {
    const type = field.property?.type;
    if (!type || !(GROUPING_PROPERTIES.has(type) || DATE_PROPERTIES.has(type))) return [];
    return [
      {
        id: field.id,
        kind: "property",
        bucket: DATE_PROPERTIES.has(type),
        label: field.label,
        property: field.property,
      },
    ];
  }),
];

/** A layout's groupings, or, where it names none, every field that groups
 *  without a bucket. */
export const groupingsOf = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  all: GroupingChoice[]
): LayoutGrouping[] =>
  groupings ??
  all
    .filter((each) => !each.bucket && !each.property && groupsBy(kind, all, each.id))
    .map((each) => ({ field: each.id }));

/** The groupings `kind` can offer, of `all`. */
export const groupingsFor = <T extends GroupingChoice>(all: T[], kind: ListLayoutReadKind): T[] =>
  all.filter((each) => groupsBy(kind, all, each.id));

const label = (content: ReactNode) => <span className="font-medium text-base">{content}</span>;

/** How a person, a tag or an option moves between groups: off the one it came
 *  from and onto the other, where the empty group has none to take or give. */
export const swap = (from: string, to: string) => ({
  add: to === NO_GROUP ? [] : [to],
  remove: from === NO_GROUP ? [] : [from],
});

/** A bucket of the calendar, named by its first day. */
const bucketLabel = (key: string, bucket: DateBucket, t: LayoutEnv["t"]): string => {
  const [year, month, day] = key.split("-").map(Number);
  const start = new Date(year, month - 1, day);
  const dayName = dateTimeFormat(undefined, { dateStyle: "medium" }).format(start);
  switch (bucket) {
    case "week":
      return t("layouts:groupings.weekOf", { date: dayName });
    case "month":
      return dateTimeFormat(undefined, { month: "long", year: "numeric" }).format(start);
    case "quarter":
      return t("layouts:groupings.quarter", { quarter: Math.floor((month - 1) / 3) + 1, year });
    case "year":
      return String(year);
    default:
      return dayName;
  }
};

const propertyMove = (
  definition: PropertyDefinitionRead
): ((from: string, to: string) => PropertyMove) | undefined => {
  const id = definition.id;
  const write = (to: string, value: unknown): PropertyMove => ({
    properties:
      to === NO_GROUP
        ? { merge: true, removed: [id] }
        : { merge: true, values: [{ property_id: id, value }] },
  });
  switch (definition.type) {
    case MetadataType.select:
      return (_from, to) => write(to, to);
    case MetadataType.multi_select:
      return (from, to) => ({
        properties: { merge: true, options: [{ property_id: id, ...swap(from, to) }] },
      });
    case MetadataType.user_reference:
      return (_from, to) => write(to, Number(to));
    case MetadataType.checkbox:
      return (_from, to) => write(to, to === "true");
    default:
      return undefined;
  }
};

/**
 * The groupings a list offers, in its order: the layout's own, or every field
 * that groups without a bucket where it names none. The one the server has
 * worked out groups for (`served`) knows its items' groups; the rest only how
 * they are offered. The kind of item draws and moves its own fields' groups
 * (`own`).
 */
export const offeredGroupings = <I extends { id: number; properties: PropertySummary[] }, M>({
  all,
  groupings,
  kind,
  items,
  own,
  served,
  t,
}: {
  all: Groupable[];
  groupings: LayoutGrouping[] | null | undefined;
  kind: ListLayoutReadKind;
  items: I[];
  own: OwnGroups<M>;
  served?: ServedGroups;
  t: LayoutEnv["t"];
}): OfferedGrouping<I, M | PropertyMove>[] => {
  const byField = new Map(groupingsFor(all, kind).map((each) => [each.id, each]));

  return groupingsOf(groupings, kind, all).flatMap((entry) => {
    const field = byField.get(entry.field);
    if (!field) return [];
    const data = served?.field === field.id ? served.data : undefined;
    const order = new Map((data?.groups ?? []).map((group, index) => [group.key, index]));
    const names = new Map((data?.groups ?? []).map((group) => [group.key, group.label]));
    const named = (key: string) => label(names.get(key) ?? key);
    const summary = (value: unknown): PropertySummary => ({
      ...propertyStubFromDefinition(field.property as PropertyDefinitionRead),
      value,
    });

    const propertyHeader = (definition: PropertyDefinitionRead, key: string): ReactNode => {
      switch (definition.type) {
        case MetadataType.checkbox:
          return label(
            t(key === "true" ? "table.checked" : "table.unchecked", { name: field.label })
          );
        case MetadataType.select:
        case MetadataType.multi_select:
          return (
            <PropertyValueCell
              summary={summary(definition.type === MetadataType.select ? key : [key])}
            />
          );
        case MetadataType.user_reference: {
          const person = items
            .map((item) =>
              extractUser(
                item.properties?.find((each) => each.property_id === definition.id)?.value
              )
            )
            .find((each) => each && String(each.id) === key);
          return person ? <PropertyValueCell summary={summary(person)} /> : named(key);
        }
        default:
          return named(key);
      }
    };

    const header = (key: string): ReactNode => {
      if (entry.bucket && key !== NO_GROUP) return label(bucketLabel(key, entry.bucket, t));
      const { property } = field;
      if (property && (key !== NO_GROUP || property.type === MetadataType.checkbox)) {
        return propertyHeader(property, key);
      }
      const drawn = property ? null : own.header(field, key);
      if (typeof drawn === "string") return label(drawn);
      if (drawn != null) return drawn;
      return key === NO_GROUP ? label(t("table.noValue", { name: field.label })) : named(key);
    };

    const grouping: ItemGrouping<I, M | PropertyMove> = {
      id: field.id,
      column: groupColumn(field.id),
      label: field.label,
      bucket: entry.bucket,
      keys: (item) => data?.rows[String(item.id)] ?? [],
      values: data?.groups.map((group) => group.key),
      compare: (a, b) => (order.get(a) ?? order.size) - (order.get(b) ?? order.size),
      header,
      move: entry.bucket
        ? undefined
        : field.property
          ? propertyMove(field.property)
          : own.move(field.id),
    };
    return [{ grouping, hidden: new Set(entry.hidden ?? []) }];
  });
};

/**
 * What a person's list is grouped by: the pick they kept, None included,
 * while the list still offers it, and otherwise the grouping the list starts
 * on. `kept` is null where they never picked.
 */
export const viewGrouping = (
  definition: Pick<ListLayoutDefinitionOutput, "groupings" | "group_by"> | undefined,
  kind: ListLayoutReadKind,
  kept: GroupingState | null,
  all: GroupingChoice[]
): GroupingState => {
  const start = definition?.group_by ? [groupColumn(definition.group_by)] : [];
  if (kept === null) return start;
  const offered = groupingsOf(definition?.groupings, kind, all)
    .filter((entry) => groupsBy(kind, all, entry.field))
    .map((entry) => groupColumn(entry.field));
  return kept.every((column) => offered.includes(column)) ? kept : start;
};

/** The grouping a list is grouped by, as the layout offers it: its field and
 *  bucket, and the groups it leaves out. */
export const activeGrouping = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  grouping: GroupingState,
  all: GroupingChoice[]
): LayoutGrouping | undefined =>
  groupingsOf(groupings, kind, all).find((entry) => grouping.includes(groupColumn(entry.field)));

/** `groupings` (the offered ones where null) with the group `key` of the one
 *  `id` names shown or left out. */
export const withGroupShown = (
  groupings: LayoutGrouping[] | null | undefined,
  kind: ListLayoutReadKind,
  all: GroupingChoice[],
  id: string,
  key: string,
  shown: boolean
): LayoutGrouping[] =>
  groupingsOf(groupings, kind, all).map((entry) => {
    if (entry.field !== id) return entry;
    const others = (entry.hidden ?? []).filter((each) => each !== key);
    return { ...entry, hidden: shown ? others : [...others, key] };
  });

/** A band of a grouped board: one group, and its items in the board's order. */
export type Band<I> = { key: string; items: I[] };

/** A board's bands: one for each group there is (the ones `values` names,
 *  holding an item or not) and each its items are in, an item in several in
 *  each, less those `hidden` leaves out, in the grouping's order. */
export const boardBands = <I, M>(
  { grouping, hidden }: OfferedGrouping<I, M>,
  items: I[]
): Band<I>[] => {
  const bands = new Map<string, I[]>((grouping.values ?? []).map((key) => [key, []]));
  for (const item of items) {
    const keys = grouping.keys(item);
    for (const key of keys.length > 0 ? keys : [NO_GROUP]) {
      const band = bands.get(key);
      if (band) band.push(item);
      else bands.set(key, [item]);
    }
  }
  return [...bands]
    .filter(([key]) => !hidden.has(key))
    .sort(([a], [b]) => grouping.compare(a, b))
    .map(([key, held]) => ({ key, items: held }));
};

/** An item as a row of a grouped table: the one group it is listed under, when
 *  the table is grouped, so a plain list of items is a valid row list. */
export type GroupRow<I> = I & { group?: string };

/** One row per group an item is in, so an item with two tags is listed under
 *  both rather than under whichever came first. */
export const groupRows = <I, M>(items: I[], grouping: ItemGrouping<I, M>): GroupRow<I>[] =>
  items.flatMap((item) => {
    const keys = grouping.keys(item);
    return (keys.length > 0 ? keys : [NO_GROUP]).map((group) => ({ ...item, group }));
  });

/** A row's id: an item listed under several groups has a row in each. */
export const groupRowId = (row: GroupRow<{ id: number }>): string =>
  row.group === undefined ? String(row.id) : `${row.id}::${row.group}`;

/** The items rows came from, each once, as the list holds them. */
export const uniqueItemsFromRows = <I extends { id: number }>(
  rows: GroupRow<I>[],
  byId: Map<number, I>
): I[] => {
  const seen = new Set<number>();
  const items: I[] = [];
  for (const row of rows) {
    if (seen.has(row.id)) {
      continue;
    }
    seen.add(row.id);
    items.push(byId.get(row.id) ?? row);
  }
  return items;
};
