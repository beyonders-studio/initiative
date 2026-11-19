import { Fragment, memo, type ReactNode, useMemo } from "react";

import type { ItemsProps, PropertySummary } from "@/api/generated/initiativeAPI.schemas";
import { getContrastingTextColor } from "@/ui/lib/contrast";
import { cn } from "@/ui/lib/utils";
import { nonEmptyPropertySummaries } from "@/ui/properties/propertyHelpers";

import {
  type FieldDef,
  fieldRenderer,
  isEmptyValue,
  type LayoutEnv,
  type LayoutVariant,
  plainValue,
  propertyFieldId,
} from "./fields";
import { Section } from "./section";

/** A view as data: a registered part, its props, and what it holds. The same
 *  shape the plug-in SDK uses for parts. */
export type LayoutNode = {
  type: string;
  props?: Record<string, unknown>;
  children?: LayoutNode[];
};

/** What a tree draws: an item, whose own properties its `properties` part
 *  shows. */
export type LayoutItem = { properties: PropertySummary[] };

/** What every item in one view shares. Made once per view, not per item, so
 *  the memoized items skip re-rendering until it changes. */
export type LayoutContext<I> = {
  /** In order: built-ins, properties in definition order, then those added
   *  beside them. */
  fields: ReadonlyMap<string, FieldDef<I>>;
  /** Parts its kind adds to those a card is drawn with, by node type. */
  parts?: Parts<I>;
  /** A board's card. */
  card?: LayoutNode;
  /** While the view is edited: the path of each part of its tree. */
  editing?: WeakMap<LayoutNode, string>;
  variant: LayoutVariant;
  env: LayoutEnv<I>;
  /** Each field and row on one line, nothing wrapping: a card whose height is
   *  reserved from its lines (`cardLines`) rather than measured. */
  oneLine?: boolean;
};

/**
 * A part turns its node into elements, drawing its children with the parts it
 * was drawn with. Parts call no hooks — they run inside the tree's render — so
 * anything that needs one is a component a part returns, as the field
 * renderers are.
 */
type Part<I> = (node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => ReactNode;

/** The parts a tree of one kind of item can hold, by node type. */
export type Parts<I> = Readonly<Record<string, Part<I>>>;

/** Draws one item through a tree. Unknown parts and fields draw nothing.
 *  While the tree is edited, each part is marked with its path, in an element
 *  that takes no box of its own, so the editor finds what was clicked. */
export const renderNode = <I,>(
  node: LayoutNode,
  item: I,
  view: LayoutContext<I>,
  parts: Parts<I>
): ReactNode => {
  const drawn = Object.hasOwn(parts, node.type) ? parts[node.type](node, item, view, parts) : null;
  const path = view.editing?.get(node);
  return path === undefined ? (
    drawn
  ) : (
    <div className="contents" data-layout-node={path}>
      {drawn}
    </div>
  );
};

const renderChildren = <I,>(
  node: LayoutNode,
  item: I,
  view: LayoutContext<I>,
  parts: Parts<I>
): ReactNode =>
  node.children?.map((child, index) => (
    // Keyed by place: a tree is fixed for the life of a view.
    <Fragment key={index}>{renderNode(child, item, view, parts)}</Fragment>
  ));

const renderField = <I,>(
  field: FieldDef<I>,
  value: unknown,
  item: I,
  view: LayoutContext<I>,
  key?: number
): ReactNode => {
  if (isEmptyValue(value)) return null;
  const Renderer = fieldRenderer(field);
  return (
    <Renderer
      key={key}
      value={value}
      item={item}
      field={field}
      variant={view.variant}
      env={view.env}
      oneLine={view.oneLine}
    />
  );
};

/** A property whose definition has not arrived: drawn all the same. */
const UNLOADED_PROPERTY: FieldDef = {
  id: "",
  kind: "property",
  source: "property",
  label: "",
  hideable: false,
  requireable: false,
  value: () => null,
};

/** A saved tree carries a prop it does not set as null, which means the same
 *  as leaving it out. */
type StackProps = {
  direction?: "column" | "row" | null;
  gap?: "xs" | "sm" | null;
  wrap?: boolean | null;
  /** In a column, items keep their own width rather than filling it; in a
   *  row, they keep their own height. */
  align?: "start" | null;
  tone?: "muted" | null;
};

const GAP = { xs: "gap-1", sm: "gap-2" };
const SPACE = { xs: "space-y-1", sm: "space-y-2" };
const TONE = { muted: "wrap-break-word text-muted-foreground text-xs" };

const stackClassName = ({ direction, gap: given, wrap, align, tone }: StackProps): string => {
  const gap = given ?? "xs";
  if (direction === "row") {
    return cn(
      "flex w-full min-w-0",
      wrap && "flex-wrap",
      align === "start" && "items-start",
      // A row holding an item's actions wraps them onto a line above the
      // rest, where reversed wrapping turns its top into the cross end.
      "item-actions-row:flex-wrap-reverse item-actions-row:items-end",
      GAP[gap]
    );
  }
  // A column whose items fill it is a plain block, spaced line by line.
  return align === "start"
    ? cn("flex w-full min-w-0 flex-col items-start text-left", GAP[gap], tone && TONE[tone])
    : cn("w-full min-w-0", SPACE[gap], tone && TONE[tone]);
};

/** While a tree is edited, a group with nothing in it still takes room, to
 *  drop a part into or add one; readers never see it. */
const emptyWhileEdited = <I,>(node: LayoutNode, view: LayoutContext<I>): ReactNode =>
  view.editing && !node.children?.length ? (
    <div className="flex min-h-10 w-full items-center justify-center rounded-md border border-dashed px-2 text-center text-muted-foreground text-xs">
      {view.env.t("layouts:emptyGroup")}
    </div>
  ) : null;

// A region of an item's layout: it draws its parts in a column, and places
// itself on the layout's grid.
const region =
  (className: string) =>
  <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => (
    <div className={cn("min-w-0", className)}>
      {renderChildren(node, item, view, parts)}
      {emptyWhileEdited(node, view)}
    </div>
  );

// Where a part of a column falls once the layout is a single column.
const ORDER: Record<number, string> = {
  1: "order-1 canvas-md:order-none",
  2: "order-2 canvas-md:order-none",
  3: "order-3 canvas-md:order-none",
  4: "order-4 canvas-md:order-none",
  5: "order-5 canvas-md:order-none",
  6: "order-6 canvas-md:order-none",
  7: "order-7 canvas-md:order-none",
  8: "order-8 canvas-md:order-none",
};

// A column of an item's layout. Until there is room for the columns side by
// side, the layout is one column and each column's parts join it, falling where
// their `order` prop puts them, so the two columns can interleave. A part
// that draws nothing takes no room.
const column =
  (className: string) =>
  <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => (
    <div className={cn("canvas-md:flex contents canvas-md:min-w-0 canvas-md:flex-col", className)}>
      {node.children?.map((child, index) => (
        <div
          // Keyed by place: a tree is fixed for the life of a view.
          key={index}
          className={cn("min-w-0 empty:hidden", ORDER[Number(child.props?.order)])}
        >
          {renderNode(child, item, view, parts)}
        </div>
      ))}
      {emptyWhileEdited(node, view)}
    </div>
  );

/** Arrangement, for a tree of any kind of item. */
export const LAYOUT_PARTS = {
  stack: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => {
    const props = (node.props ?? {}) as StackProps;
    return (
      <div className={stackClassName(view.oneLine ? { ...props, wrap: false } : props)}>
        {renderChildren(node, item, view, parts)}
        {emptyWhileEdited(node, view)}
      </div>
    );
  },
  /** An item's layout, which holds its header, main and side regions. */
  layout: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => (
    <div className="grid canvas-md:grid-cols-[minmax(0,1fr)_20rem] gap-6">
      {renderChildren(node, item, view, parts)}
    </div>
  ),
  header: region("space-y-2 canvas-md:col-span-2"),
  main: column("canvas-md:col-start-1 canvas-md:row-start-2 canvas-md:gap-6"),
  side: column("canvas-md:col-start-2 canvas-md:row-start-2 canvas-md:gap-4"),
  /** A bordered group of parts, titled in the initiative's own words. */
  section: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => (
    <Section
      title={typeof node.props?.title === "string" ? node.props.title : undefined}
      collapsed={node.props?.collapsed === true}
    >
      {renderChildren(node, item, view, parts)}
      {emptyWhileEdited(node, view)}
    </Section>
  ),
};

const HEX_DIGITS = "0123456789abcdefABCDEF";

/** The colour an item's field `fieldId` holds (`#rrggbb`), or none. */
export const tintOf = <I,>(
  fieldId: unknown,
  item: I,
  fields: ReadonlyMap<string, FieldDef<I>>
): string | undefined => {
  if (typeof fieldId !== "string") return undefined;
  const value = plainValue(fields.get(fieldId)?.value(item));
  return typeof value === "string" &&
    value.length === 7 &&
    value[0] === "#" &&
    [...value.slice(1)].every((digit) => HEX_DIGITS.includes(digit))
    ? value
    : undefined;
};

/** Drawn in `color`, its words legible on it. */
const tinted = (color: string) => ({
  backgroundColor: color,
  color: getContrastingTextColor(color),
});

/** The first items of one of an item's item tables, each a line of the
 *  fields the part names, drawn in its own colour where the part says. */
const ItemsPreview = <I,>({
  props,
  item,
  view,
}: {
  props: ItemsProps;
  item: I;
  view: LayoutContext<I>;
}) => {
  const preview = view.env.itemPreview?.(item, props.item, props.limit);
  if (!preview?.items.length) return null;
  const lines: LayoutContext<unknown> = {
    fields: preview.fields,
    variant: view.variant,
    env: preview.env,
    oneLine: true,
  };
  return (
    <ul className="w-full min-w-0 space-y-1">
      {preview.items.slice(0, props.limit).map((child, index) => {
        const color = tintOf(props.tint, child, preview.fields);
        return (
          <li
            // Keyed by place: the items keep their own order.
            key={index}
            className="flex min-w-0 items-center gap-2 rounded-sm bg-muted px-1.5 py-0.5 text-xs"
            style={color ? tinted(color) : undefined}
          >
            {props.fields.map((id) => {
              const field = preview.fields.get(id);
              return field ? (
                <Fragment key={id}>{renderField(field, field.value(child), child, lines)}</Fragment>
              ) : null;
            })}
          </li>
        );
      })}
    </ul>
  );
};

const PARTS = {
  ...LAYOUT_PARTS,
  // The board draws the card's frame, which carries the drag and the measuring;
  // the card lays out what is inside it, in the colour its `tint` field holds.
  card: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>, parts: Parts<I>) => {
    const color = tintOf(node.props?.tint, item, view.fields);
    const children = renderChildren(node, item, view, parts);
    return color ? (
      <div className="w-full min-w-0 space-y-1 rounded-md p-2" style={tinted(color)}>
        {children}
      </div>
    ) : (
      children
    );
  },
  // A row's first items of one of its item tables.
  items: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>) =>
    node.props ? (
      <ItemsPreview props={node.props as unknown as ItemsProps} item={item} view={view} />
    ) : null,
  field: <I,>(node: LayoutNode, item: I, view: LayoutContext<I>) => {
    const field = view.fields.get(String(node.props?.field));
    return field ? renderField(field, field.value(item), item, view) : null;
  },
  // Every property the item carries, in its own order: a shipped tree cannot
  // name them.
  properties: <I extends LayoutItem>(_node: LayoutNode, item: I, view: LayoutContext<I>) =>
    nonEmptyPropertySummaries(item.properties).map((summary) =>
      renderField<I>(
        view.fields.get(propertyFieldId(summary.property_id)) ?? UNLOADED_PROPERTY,
        summary,
        item,
        view,
        summary.property_id
      )
    ),
};

/** Whether a tree draws a field. */
export const namesField = (node: LayoutNode, fieldId: string): boolean =>
  (node.type === "field" && node.props?.field === fieldId) ||
  (node.children ?? []).some((child) => namesField(child, fieldId));

type TreeProps<I> = { node: LayoutNode; item: I; view: LayoutContext<I> };

/** Draws one item of a collection through a tree. `memo` keeps no type
 *  parameter, so the tree is typed again by the item it draws. */
export const LayoutTree = memo(function LayoutTree<I extends LayoutItem>({
  node,
  item,
  view,
}: TreeProps<I>) {
  const parts = useMemo(() => (view.parts ? { ...PARTS, ...view.parts } : PARTS), [view.parts]);
  return renderNode(node, item, view, parts);
}) as <I extends LayoutItem>(props: TreeProps<I>) => ReactNode;
