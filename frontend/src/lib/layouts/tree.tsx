import { Fragment, memo, type ReactNode } from "react";

import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { cn } from "@/lib/utils";

import {
  FIELD_RENDERERS,
  type FieldDef,
  isEmptyValue,
  type LayoutEnv,
  type LayoutItem,
  type LayoutVariant,
  propertyFieldId,
} from "./fields";
import { type PluginItem, type PluginOnItems, PluginPartView } from "./plugins";
import { Section } from "./section";

/** A view as data: a registered part, its props, and what it holds. The same
 *  shape the plug-in SDK uses for parts. */
export type LayoutNode = {
  type: string;
  props?: Record<string, unknown>;
  children?: LayoutNode[];
};

/** What every item in one view shares. Made once per view, not per item, so
 *  the memoized items skip re-rendering until it changes. */
export type LayoutContext = {
  /** In order: built-ins, properties in definition order, then plug-ins'. */
  fields: ReadonlyMap<string, FieldDef>;
  /** The plug-ins whose parts a tree may place, by install. */
  plugins?: ReadonlyMap<number, PluginOnItems>;
  /** A board's card. */
  card?: LayoutNode;
  /** While the view is edited: the path of each part of its tree. */
  editing?: WeakMap<LayoutNode, string>;
  variant: LayoutVariant;
  env: LayoutEnv;
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
type Part<I> = (node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => ReactNode;

/** The parts a tree of one kind of item can hold, by node type. */
export type Parts<I> = Readonly<Record<string, Part<I>>>;

/** Draws one item through a tree. Unknown parts and fields draw nothing.
 *  While the tree is edited, each part is marked with its path, in an element
 *  that takes no box of its own, so the editor finds what was clicked. */
export const renderNode = <I,>(
  node: LayoutNode,
  item: I,
  view: LayoutContext,
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
  view: LayoutContext,
  parts: Parts<I>
): ReactNode =>
  node.children?.map((child, index) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: a tree is fixed for the life of a view
    <Fragment key={index}>{renderNode(child, item, view, parts)}</Fragment>
  ));

const renderField = (
  field: FieldDef,
  value: unknown,
  item: LayoutItem,
  view: LayoutContext,
  key?: number
): ReactNode => {
  if (isEmptyValue(value)) return null;
  const Renderer = FIELD_RENDERERS[field.kind];
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
const emptyWhileEdited = (node: LayoutNode, view: LayoutContext): ReactNode =>
  view.editing && !node.children?.length ? (
    <div className="flex min-h-10 w-full items-center justify-center rounded-md border border-dashed px-2 text-center text-muted-foreground text-xs">
      {view.env.t("layouts:emptyGroup")}
    </div>
  ) : null;

// A region of an item's layout: it draws its parts in a column, and places
// itself on the layout's grid.
const region =
  (className: string) =>
  <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
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
  <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
    <div className={cn("canvas-md:flex contents canvas-md:min-w-0 canvas-md:flex-col", className)}>
      {node.children?.map((child, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: a tree is fixed for the life of a view
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
  stack: <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => {
    const props = (node.props ?? {}) as StackProps;
    return (
      <div className={stackClassName(view.oneLine ? { ...props, wrap: false } : props)}>
        {renderChildren(node, item, view, parts)}
        {emptyWhileEdited(node, view)}
      </div>
    );
  },
  /** An item's layout, which holds its header, main and side regions. */
  layout: <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
    <div className="grid canvas-md:grid-cols-[minmax(0,1fr)_20rem] gap-6">
      {renderChildren(node, item, view, parts)}
    </div>
  ),
  header: region("space-y-2 canvas-md:col-span-2"),
  main: column("canvas-md:col-start-1 canvas-md:row-start-2 canvas-md:gap-6"),
  side: column("canvas-md:col-start-2 canvas-md:row-start-2 canvas-md:gap-4"),
  /** One of a plug-in's parts, on whatever kind of item the plug-ins were
   *  read for. */
  plugin: <I,>(node: LayoutNode, item: I, view: LayoutContext) => (
    <PluginPartView
      plugins={view.plugins}
      pluginId={Number(node.props?.plugin)}
      partId={String(node.props?.part)}
      item={item as PluginItem}
    />
  ),
  /** A bordered group of parts, titled in the initiative's own words. */
  section: <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
    <Section
      title={typeof node.props?.title === "string" ? node.props.title : undefined}
      collapsed={node.props?.collapsed === true}
    >
      {renderChildren(node, item, view, parts)}
      {emptyWhileEdited(node, view)}
    </Section>
  ),
};

const PARTS: Parts<LayoutItem> = {
  ...LAYOUT_PARTS,
  // The board draws the card's frame, which carries the drag and the measuring;
  // the card lays out what is inside it.
  card: (node, item, view, parts) => renderChildren(node, item, view, parts),
  field: (node, item, view) => {
    const field = view.fields.get(String(node.props?.field));
    return field ? renderField(field, field.value(item), item, view) : null;
  },
  // Every property the item carries, in its own order: a shipped tree cannot
  // name them.
  properties: (_node, item, view) =>
    nonEmptyPropertySummaries(item.properties).map((summary) =>
      renderField(
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

/** Draws one item of a collection through a tree. */
export const LayoutTree = memo(function LayoutTree({
  node,
  item,
  view,
}: {
  node: LayoutNode;
  item: LayoutItem;
  view: LayoutContext;
}) {
  return renderNode(node, item, view, PARTS);
});
