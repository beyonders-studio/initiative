import type {
  ControlKind,
  FieldDescription,
  FilterOp as GeneratedFilterOp,
} from "@/api/generated/initiativeAPI.schemas";
import { FilterOp as FilterOpValues } from "@/api/generated/initiativeAPI.schemas";

/**
 * The filter half of a data view.
 *
 * A binding's `conditions` are the app's own filter DSL — the same one the
 * tasks endpoint parses, under the viewer's own session. They have been
 * accepted and stored since dashboards shipped; what has never existed is a way
 * to *author* one or to *read* one back, which is why every task-backed widget
 * shows every task in the initiative.
 *
 * Two things live here and nowhere else:
 *
 * 1. **The field catalog** — which fields a dashboard may filter on, what kind
 *    of value each takes, and which operators apply. It is a subset of what the
 *    endpoint accepts (every `Task` column plus four virtual fields), chosen
 *    for what makes sense on a dashboard rather than mirroring the whole model.
 * 2. **Relative dates.** The DSL's values are literals, so a stored
 *    `due_date < 2026-09-30` is stale the day after someone saves it — useless
 *    on a dashboard, which is a standing question rather than a snapshot. A
 *    value may instead be `{relative: "+30d"}`, kept relative in the definition
 *    and expanded to an absolute instant by {@link expandConditions} on the way
 *    to the wire. The server never sees the relative form and needs no
 *    knowledge of it.
 *
 * Nothing here validates: the endpoint's own parser owns its limits (50
 * conditions, group depth 3), and re-stating them would mean maintaining them
 * twice. This drops what it cannot read and passes the rest through.
 */

/** Operators the endpoint's DSL understands, and the controls that pick a
 *  value. Both come from the server's own enums through the generated client,
 *  so neither is restated here. Negation is a flag on the condition, not a
 *  separate operator. */
export type FilterOp = GeneratedFilterOp;
/** Every operator, for reading a stored condition back. Derived from the
 *  generated enum rather than restated, so the server's vocabulary is the only
 *  one there is. */
export const FILTER_OPS = Object.values(FilterOpValues) as readonly FilterOp[];

/** A date expressed as an offset from "now", in days. Resolved at fetch time so
 *  a saved dashboard keeps asking the same *question* as the days pass. */
export interface RelativeDate {
  relative: number;
}

export type ConditionValue = string | number | boolean | null | (string | number)[] | RelativeDate;

export interface FilterLeaf {
  field: string;
  op: FilterOp;
  value?: ConditionValue;
  negate?: boolean;
}

export interface FilterGroup {
  logic: "and" | "or";
  conditions: FilterNode[];
}

export type FilterNode = FilterLeaf | FilterGroup;

export const isGroup = (node: FilterNode): node is FilterGroup =>
  typeof node === "object" && node !== null && Array.isArray((node as FilterGroup).conditions);

export const isRelativeDate = (value: unknown): value is RelativeDate =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as RelativeDate).relative === "number";

// --- the field declarations -------------------------------------------------

/** How a value is chosen, and therefore how it is rendered back. The server's
 *  own control vocabulary, through the generated client. */
export type FieldKind = ControlKind;

export interface FilterFieldSpec {
  field: string;
  kind: FieldKind;
  ops: readonly FilterOp[];
  /** Whether the control picks several values at once. */
  multiple?: boolean;
  /** The values this field accepts, when it accepts a closed set of them.
   *  Sent by the server, read off the column that stores them — so a value
   *  added by a migration is offered here without a frontend release. */
  options?: readonly string[];
  /** What it is called, for a field that is not one of the registry's own:
   *  a range's column, named by its header as written. */
  label?: string;
}

/** Where a closed vocabulary's labels live, by the field that holds it.
 *
 *  The *values* arrive from the server; only their wording is ours, and these
 *  two vocabularies are already translated for the task UI. A field absent here
 *  renders its raw value, which is what a newly added enum should do until
 *  somebody writes words for it. */
const OPTION_LABEL_NAMESPACES: Record<string, string> = {
  status_category: "tasks:statusCategory",
  priority: "tasks:priority",
};

/** The translation key for one option of a closed vocabulary. */
export const optionLabelKey = (field: string, value: string | number): string => {
  const namespace = OPTION_LABEL_NAMESPACES[field];
  return namespace ? `${namespace}.${value}` : String(value);
};

/** The server's description, in the shape the controls read.
 *
 *  The two differ in one key: `name` there, `field` here, because that is what
 *  a stored condition has always called it. Everything else passes through —
 *  the kinds and operators are already the server's enums, so there is nothing
 *  to translate and nothing that could disagree. */
export const toFilterFieldSpec = (described: FieldDescription): FilterFieldSpec => ({
  field: described.name,
  kind: described.kind,
  ops: described.ops,
  multiple: described.multiple,
  options: described.options,
});

/** One field, found by name. Takes the list because these are pure functions
 *  and the list is fetched — the same reason a formatter takes `t`. */
export const fieldSpec = (
  fields: readonly FilterFieldSpec[],
  field: string
): FilterFieldSpec | undefined => fields.find((candidate) => candidate.field === field);

// --- reading ----------------------------------------------------------------

const readValue = (raw: unknown): ConditionValue | undefined => {
  if (raw === null) return null;
  if (isRelativeDate(raw)) return { relative: raw.relative };
  if (Array.isArray(raw)) {
    return raw.filter(
      (entry): entry is string | number => typeof entry === "string" || typeof entry === "number"
    );
  }
  if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") return raw;
  return undefined;
};

const readNode = (raw: unknown, depth: number): FilterNode | undefined => {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;

  if (Array.isArray(record.conditions)) {
    // The endpoint caps group nesting; a definition deeper than that would 400
    // the whole query, so an over-deep group is dropped rather than sent.
    if (depth >= 1) return undefined;
    const children = record.conditions
      .map((child) => readNode(child, depth + 1))
      .filter((child): child is FilterNode => Boolean(child));
    if (!children.length) return undefined;
    return { logic: record.logic === "or" ? "or" : "and", conditions: children };
  }

  if (typeof record.field !== "string") return undefined;
  const op = FILTER_OPS.includes(record.op as FilterOp) ? (record.op as FilterOp) : undefined;
  if (!op) return undefined;
  const value = readValue(record.value);
  return {
    field: record.field,
    op,
    ...(value === undefined ? {} : { value }),
    ...(record.negate === true ? { negate: true } : {}),
  };
};

/** A stored `conditions` value as a typed list. Tolerates the single-group form
 *  a definition may carry, and drops anything unreadable. */
export const readConditions = (raw: unknown): FilterNode[] => {
  if (Array.isArray(raw)) {
    return raw.map((node) => readNode(node, 0)).filter((node): node is FilterNode => Boolean(node));
  }
  const single = readNode(raw, 0);
  return single ? [single] : [];
};

/** How many comparisons a filter makes, counted through groups — the number the
 *  provenance line shows. */
export const countLeaves = (nodes: FilterNode[]): number =>
  nodes.reduce((total, node) => total + (isGroup(node) ? countLeaves(node.conditions) : 1), 0);

// --- writing ----------------------------------------------------------------

const DAY = 86_400_000;

/**
 * Resolve relative dates against a given instant.
 *
 * Called on the way to the wire, never on the way to storage: the definition
 * keeps `{relative: 30}` so the question stays "due within 30 days", and the
 * endpoint receives the instant that means today.
 */
export const expandConditions = (nodes: FilterNode[], now: number): FilterNode[] =>
  nodes.map((node) => {
    if (isGroup(node)) {
      return { ...node, conditions: expandConditions(node.conditions, now) };
    }
    if (!isRelativeDate(node.value)) return node;
    return { ...node, value: new Date(now + node.value.relative * DAY).toISOString() };
  });
