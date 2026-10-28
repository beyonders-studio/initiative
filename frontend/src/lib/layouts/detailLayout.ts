/**
 * A detail (a task's, an event's) laid out from a tree: its regions, where
 * each part falls once the detail is one column, and the layout a detail is
 * stored as. What a layout leaves out is not shown.
 */

import { createContext } from "react";

import type {
  DetailLayoutDefinitionInput,
  DetailLayoutRead,
  PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { isEmptyPropertyValue } from "@/components/properties/propertyHelpers";

import { PROPERTY_FIELD_PREFIX } from "./fields";
import type { LayoutNode } from "./tree";

/** A detail's regions, in the order a detail holds them. */
export const LAYOUT_REGIONS = ["header", "main", "side"] as const;

export type Region = (typeof LAYOUT_REGIONS)[number];

/** A detail layout's regions, as stored: one it leaves out is drawn as shipped. */
export type StoredRegions = Partial<Record<Region, LayoutNode[] | null>>;

/** The properties a detail places on their own, by definition id: All
 *  properties leaves them out. */
export const placedProperties = (root: LayoutNode): Set<number> =>
  new Set(
    nodesIn(root.children ?? [])
      .map((node) => String(node.props?.field ?? ""))
      .filter((field) => field.startsWith(PROPERTY_FIELD_PREFIX))
      .map((field) => Number(field.slice(PROPERTY_FIELD_PREFIX.length)))
  );

/** What the detail being drawn places on its own, for All properties. */
export const PlacedProperties = createContext<ReadonlySet<number>>(new Set());

/** What a part is required by, where it can be: a field by its id, one of
 *  the detail's own parts (a task's dates) by its type. */
export const requiredKey = (node: LayoutNode): string =>
  node.type === "field" ? String(node.props?.field) : node.type;

/** Whether the layout requires the part to be filled in. */
export const isRequired = (node: LayoutNode): boolean => node.props?.required === true;

/** What a stored detail requires, in the order it places them: each region as
 *  stored, none where it is drawn as shipped, which requires nothing. */
export const requiredKeys = (stored: StoredRegions | null | undefined): string[] => [
  ...new Set(
    LAYOUT_REGIONS.flatMap((region) => nodesIn(stored?.[region] ?? []))
      .filter(isRequired)
      .map(requiredKey)
  ),
];

/** Whether one of `properties` holds a value for the property `key` names. */
export const propertyFilled = (properties: readonly PropertySummary[], key: string): boolean =>
  key.startsWith(PROPERTY_FIELD_PREFIX) &&
  properties.some(
    (each) =>
      each.property_id === Number(key.slice(PROPERTY_FIELD_PREFIX.length)) &&
      !isEmptyPropertyValue(each.value)
  );

/** A field's value once `sent` (changes not yet saved, as an item being added
 *  holds them) is applied: what it sends for `key`, or else what `held` says. */
export const sentOr = <P, K extends keyof P>(sent: Partial<P>, key: K, held: unknown): unknown =>
  Object.hasOwn(sent, key) ? sent[key] : held;

/** Whether a value holds text. */
export const hasText = (value: unknown): boolean =>
  typeof value === "string" && value.trim() !== "";

/** Whether a value is a list holding something. */
export const hasAny = (value: unknown): boolean => Array.isArray(value) && value.length > 0;

/** How an item of one kind reads as filled for a required key, with what is
 *  being sent for it applied: by its own reader for the key, or else by the
 *  value its `properties` hold. */
export const filledBy =
  <I, P>(
    readers: Readonly<Record<string, (item: I, sent: Partial<P>) => boolean>>,
    properties: (item: I) => readonly PropertySummary[]
  ) =>
  (item: I, key: string, sent: Partial<P> = {}): boolean =>
    Object.hasOwn(readers, key) ? readers[key](item, sent) : propertyFilled(properties(item), key);

/**
 * What of `keys` an item leaves empty, by `filled`. A property only while
 * `definitions` still has it: one since deleted requires nothing, and until
 * they are read, every property counts as empty.
 */
export const missingRequired = (
  keys: readonly string[],
  filled: (key: string) => boolean,
  definitions: readonly { id: number }[] | undefined
): string[] => {
  const known = new Set(definitions?.map((each) => each.id));
  return keys.filter((key) => {
    if (definitions && key.startsWith(PROPERTY_FIELD_PREFIX)) {
      if (!known.has(Number(key.slice(PROPERTY_FIELD_PREFIX.length)))) return false;
    }
    return !filled(key);
  });
};

/** `node` marked required, or not: a part that is not keeps no flag. */
export const withRequired = (node: LayoutNode, required: boolean): LayoutNode => {
  const { required: _was, ...props } = node.props ?? {};
  const kept = required ? { ...props, required: true } : props;
  const { props: _props, ...rest } = node;
  return Object.keys(kept).length > 0 ? { ...rest, props: kept } : rest;
};

/** A part of a detail's column, and where it falls once the detail is one column. */
export const at = (order: number, node: LayoutNode): LayoutNode => ({
  ...node,
  props: { ...node.props, order },
});

const placedAs = (node: LayoutNode) =>
  node.type === "field" ? `field:${String(node.props?.field)}` : node.type;

const nodesIn = (nodes: LayoutNode[]): LayoutNode[] =>
  nodes.flatMap((node) => [node, ...nodesIn(node.children ?? [])]);

/** What a column's part is known by: its kind or field, or a group's first. */
const anchorOf = (node: LayoutNode): string | undefined =>
  node.type === "section" || node.type === "stack"
    ? (node.children ?? []).map(anchorOf).find((anchor) => anchor !== undefined)
    : placedAs(node);

/** A part without the shipped detail's one-column `order`, at any depth: a
 *  shipped part may have been moved into a section. */
const withoutOrder = ({ props, children, ...node }: LayoutNode): LayoutNode => {
  const { order: _order, ...rest } = props ?? {};
  return {
    ...node,
    ...(Object.keys(rest).length > 0 ? { props: rest } : {}),
    ...(children ? { children: children.map(withoutOrder) } : {}),
  };
};

/** The layout a detail tree is stored as. Every region is stored, and without
 *  the shipped detail's one-column `order`: a stored region keeps its own. */
export const storedLayout = (root: LayoutNode): DetailLayoutDefinitionInput => {
  const region = (index: number) => (root.children?.[index]?.children ?? []).map(withoutOrder);
  return {
    header: region(0),
    main: region(1),
    side: region(2),
  } as DetailLayoutDefinitionInput;
};

/**
 * A detail's parts in the order a page reads them on one column: the header's,
 * then the columns' by where each falls (`order`, main ahead of side where
 * they fall together), each part's own parts inside it. A field is named by
 * its field, any other part by its kind. A plug-in's part, which only a browser
 * draws, is left out. What an export of the page draws, top to bottom.
 */
export const pageParts = (tree: LayoutNode): string[] => {
  const [header, main, side] = tree.children ?? [];
  const columns = [...(main?.children ?? []), ...(side?.children ?? [])]
    .map((node, index) => ({ node, index }))
    .sort(
      (a, b) =>
        Number(a.node.props?.order ?? 0) - Number(b.node.props?.order ?? 0) || a.index - b.index
    )
    .map(({ node }) => node);
  const walk = (node: LayoutNode): string[] => {
    if (node.type === "plugin") return [];
    if (node.type === "field") return [String(node.props?.field)];
    return node.children ? node.children.flatMap(walk) : [node.type];
  };
  return [...(header?.children ?? []), ...columns].flatMap(walk);
};

/** The parts any detail lays out with, as against its own. */
const LAYOUT_PARTS = new Set(["section", "stack", "field", "properties", "plugin"]);

/** One kind of detail: as shipped, and as a stored layout draws it. */
export interface DetailLayoutSpec {
  /** What its layout is stored as. */
  kind: DetailLayoutRead["kind"];
  /** The regions as shipped. */
  shipped: Record<Region, LayoutNode[]>;
  /** The detail's own parts, each placed at most once: what the shipped
   *  detail draws beside its fields and the parts that lay them out. */
  ownParts: string[];
  /** The built-in fields it edits: those the shipped detail places. */
  detailFields: ReadonlySet<string>;
  /** Whether a part edits a field: taken off, the field is hidden. */
  editsAField: (node: LayoutNode) => boolean;
  /** Its own parts a layout can require (a task's dates), beside the fields
   *  that are `requireable`; null for a detail that requires nothing. */
  requiredParts: ReadonlySet<string> | null;
  /** The detail as one tree to edit by path: the detail, holding its header,
   *  main and side in that order. `more` is what a shipped side draws after
   *  its own: the placed plug-ins'. */
  root: (stored: StoredRegions | null | undefined, more?: LayoutNode[]) => LayoutNode;
  /**
   * The detail from a stored layout: each region as stored, or as shipped where
   * the layout leaves it out. A stored part carries no `order`: where it falls
   * on one column is worked out here, so a detail laid out anew still reads as
   * the shipped one does on a phone.
   */
  tree: (stored: StoredRegions | null | undefined, more?: LayoutNode[]) => LayoutNode;
}

/**
 * A kind of detail, from how it ships: its regions, with each column
 * part's one-column `order`, and the part types that edit a field.
 */
export const detailLayoutSpec = ({
  kind,
  shipped,
  fieldParts,
  requiredParts = null,
  knows = shipped,
}: {
  kind: DetailLayoutRead["kind"];
  shipped: Record<Region, LayoutNode[]>;
  fieldParts: readonly string[];
  /** Its own parts a layout can require; none where it requires nothing. */
  requiredParts?: readonly string[] | null;
  /** Every part and field the detail has, where `shipped` leaves some out: a
   *  task page shaped for an idea still has dates to place. */
  knows?: Record<Region, LayoutNode[]>;
}): DetailLayoutSpec => {
  const editing = new Set(fieldParts);
  const editsAField = (node: LayoutNode) => editing.has(node.type);
  const knownNodes = nodesIn(Object.values(knows).flat());
  /** Where the shipped detail puts each of its column parts on one column. */
  const shippedOrder = new Map(
    [...shipped.main, ...shipped.side].map((node) => [anchorOf(node), Number(node.props?.order)])
  );

  /**
   * A column's parts with where each falls once the detail is one column, as
   * the shipped detail interleaves its columns: a part the shipped detail has
   * falls where it puts it, any other right after the part before it, and a
   * column keeps its own order (a part never falls before one above it).
   * Parts that fall together keep the main column's ahead of the side's.
   */
  const ordered = (parts: LayoutNode[], column: "main" | "side"): LayoutNode[] => {
    const known = parts.map((part) => shippedOrder.get(anchorOf(part)));
    let order =
      known.find((each) => each !== undefined) ?? Number(shipped[column][0]?.props?.order ?? 1);
    return parts.map((part, index) => {
      order = Math.max(order, known[index] ?? order);
      return at(order, part);
    });
  };

  const regionsOf = (
    stored: StoredRegions | null | undefined,
    more: LayoutNode[] = []
  ): Record<Region, LayoutNode[]> => ({
    header: stored?.header ?? shipped.header,
    main: stored?.main ?? shipped.main,
    side: stored?.side ?? [...shipped.side, ...more],
  });

  return {
    kind,
    shipped,
    ownParts: [
      ...new Set(knownNodes.map((node) => node.type).filter((type) => !LAYOUT_PARTS.has(type))),
    ],
    detailFields: new Set(
      knownNodes.filter((node) => node.type === "field").map((node) => String(node.props?.field))
    ),
    editsAField,
    requiredParts: requiredParts ? new Set(requiredParts) : null,
    root: (stored, more) => {
      const regions = regionsOf(stored, more);
      return {
        type: "layout",
        children: LAYOUT_REGIONS.map((region) => ({ type: region, children: regions[region] })),
      };
    },
    tree: (stored, more) => {
      const regions = regionsOf(stored, more);
      return {
        type: "layout",
        children: [
          { type: "header", children: regions.header },
          { type: "main", children: ordered(regions.main, "main") },
          { type: "side", children: ordered(regions.side, "side") },
        ],
      };
    },
  };
};

/**
 * A detail as an item being added draws it, on one column: its header, the
 * fields and parts named up front (by `requiredKey`) wherever its side places
 * them, then its main column,
 * with the rest of its side folded under `more`. A group the fields up front
 * leave empty goes with them.
 */
export const addingTree = (tree: LayoutNode, upFront: readonly string[]): LayoutNode => {
  const region = (type: Region) =>
    tree.children?.find((each) => each.type === type)?.children ?? [];
  const pulled: LayoutNode[] = [];
  const without = (nodes: LayoutNode[]): LayoutNode[] =>
    nodes.flatMap((node) => {
      if (!node.children && upFront.includes(requiredKey(node))) {
        pulled.push(node);
        return [];
      }
      if (!node.children?.length) return [node];
      const children = without(node.children);
      return children.length === 0 ? [] : [{ ...node, children }];
    });
  const rest = without(region("side"));
  return {
    type: "adding",
    children: [
      ...region("header"),
      ...pulled,
      ...region("main"),
      ...(rest.length > 0 ? [{ type: "more", children: rest }] : []),
    ],
  };
};
