import type { FlatNamespace } from "i18next";
import { ChevronDown, CircleAlert } from "lucide-react";
import {
  type ComponentType,
  createContext,
  Fragment,
  type ReactNode,
  useContext,
  useId,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { type MetadataOwner, ownProperties } from "@/ui/properties/propertyHelpers";

import {
  addingTree,
  type DetailLayoutSpec,
  isRequired,
  PlacedProperties,
  placedProperties,
  requiredKey,
  requiredKeys,
  type StoredRegions,
} from "./detailLayout";
import { indexPaths } from "./draft";
import { ItemDraftContext } from "./editing";
import { type ItemSaves, PlacedPropertyField, PropertiesField } from "./fieldEditors";
import { type FieldDef, type LayoutEnv, PROPERTY_FIELD_PREFIX } from "./fields";
import { LAYOUT_PARTS, type LayoutContext, type LayoutNode, type Parts, renderNode } from "./tree";

/** What every kind of item drawn on a detail has. */
export type DetailItem = { id: number; properties: PropertySummary[]; updated_at?: string };

/** Where one item lives, which the parts every item's detail has read. */
export interface ItemHome<I, P> {
  /** How its properties are saved, each on its own. */
  saves: ItemSaves<I, P>;
  /** The server says the reader cannot change it. */
  readOnly: boolean;
  /** Its initiative, which holds its properties' definitions; none for a
   *  community's own tool. */
  initiativeId: number | null;
  /** The tool it is opened in: whose members a person-valued property names. */
  canOpen: { tool: Tool; id: number };
  /** The project whose metadata it holds beside its initiative's properties:
   *  a task's. */
  owner?: MetadataOwner;
  /** The menu of what else can be done with it. */
  actions?: ReactNode;
}

/**
 * What the app drawing a kind's details adds to each, read as a hook while
 * one is drawn: what its fields are drawn with, fields and parts beside the
 * kind's own, and what a side drawn as shipped places after its own.
 */
export interface DetailExtension<I> {
  env: LayoutEnv;
  /** Fields beside the kind's own: what its `fields` is given beside its
   *  initiative's properties. */
  fields: FieldDef[];
  /** Parts a side drawn as shipped places after its own. */
  more: LayoutNode[];
  /** Parts beside those every item's detail has, which the kind's own may
   *  replace. One being added draws them all, so each draws what it does
   *  then. */
  parts: Parts<I>;
  /** Draws a field the kind has no editor of its own for: one this adds. */
  field: (field: FieldDef, item: I) => ReactNode;
  /** The detail, drawn from `tree`, inside what its parts read. */
  wrap: (tree: LayoutNode, children: ReactNode) => ReactNode;
}

/**
 * One kind of item's detail: its layout, its own fields' editors and parts,
 * and where an item of it lives. The fields placed from its initiative's
 * properties, its properties and its actions are drawn alike for every kind;
 * what the app adds to each is its extension's. `H` is what the kind says of
 * where an item lives that its extension reads.
 */
export interface DetailKind<I extends DetailItem, C, P, H extends object = object> {
  spec: DetailLayoutSpec;
  /** For a kind laid out once per type of item (a task): the type an item is,
   *  whose stored page is its own, and the page its type is drawn as until
   *  that is changed. */
  typed?: { typeOf: (item: I) => number; spec: (item: I) => DetailLayoutSpec };
  /** Its fields, given its initiative's properties and the fields its
   *  extension adds. */
  fields: (definitions: PropertyDefinitionRead[], added: FieldDef[]) => Map<string, FieldDef>;
  /** Where its fields' labels are worded. */
  namespaces: readonly FlatNamespace[];
  /** Its own fields' editors, by field id. */
  editors: Readonly<Record<string, ComponentType<{ item: I; label: string }>>>;
  /** Its own parts, beside those every item has. */
  parts?: Parts<I>;
  home: (item: I, context: C) => ItemHome<I, P> & H;
  /** What the app drawing it adds to each item's detail, given where the
   *  item lives and the kind its layout is stored as. */
  useExtension: (home: ItemHome<I, P>, kind: DetailLayoutSpec["kind"]) => DetailExtension<I>;
  /** Holds what its parts keep across a change of layout. */
  Shell?: ComponentType<{ context: C; children: ReactNode }>;
  /** Its own parts an item being added draws: those that need nothing saved. */
  addingParts?: readonly string[];
  /** Where an item being added is drawn on one column, with its side folded
   *  under More options: the fields of its side drawn up front all the same,
   *  and every field its layout requires. Without it, one being added is
   *  drawn as its page is. */
  addingUpFront?: readonly string[];
  /** Whether an item fills in what its layout can require, by its key
   *  (`requiredKey`), with what is being sent for it (an item being added)
   *  applied: a kind whose layout requires nothing has none. */
  filled?: (item: I, key: string, sent?: Partial<P>) => boolean;
}

interface Drawn {
  detail: DetailKind<DetailItem, unknown, unknown>;
  context: unknown;
  home: ItemHome<DetailItem, unknown>;
  extension: DetailExtension<DetailItem>;
}

const DrawnItem = createContext<Drawn | null>(null);

const useDrawn = (): Drawn => {
  const drawn = useContext(DrawnItem);
  if (!drawn) throw new Error("An item's detail part is drawn outside its detail");
  return drawn;
};

/** What the page drawing the item gave its detail. */
export const useItemContext = <C,>(): C => useDrawn().context as C;

/** Where the item being drawn lives, with what its kind says of it beside
 *  what every detail reads (`H`). */
export const useItemHome = <H extends object = object>(): ItemHome<unknown, unknown> & H =>
  useDrawn().home as unknown as ItemHome<unknown, unknown> & H;

const propertiesOf = (
  item: DetailItem,
  home: ItemHome<DetailItem, unknown>,
  view: LayoutContext
) => ({
  saves: home.saves,
  env: view.env.properties,
  id: item.id,
  properties: item.properties,
  readOnly: home.readOnly,
  initiativeId: home.initiativeId,
  canOpen: home.canOpen,
  owner: home.owner,
  updatedAt: item.updated_at,
});

/** One field, by its id: one of its initiative's properties, the kind's own,
 *  or one its extension adds. */
const ItemField = ({ id, item, view }: { id: string; item: DetailItem; view: LayoutContext }) => {
  const { detail, home, extension } = useDrawn();
  const t = useTranslation(detail.namespaces).t as (
    key: string,
    options?: Record<string, unknown>
  ) => string;
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return home.initiativeId === null ? null : (
      <PlacedPropertyField
        {...propertiesOf(item, home, view)}
        propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))}
      />
    );
  }
  const field = view.fields.get(id);
  if (!field) return null;
  const Editor = Object.hasOwn(detail.editors, id) ? detail.editors[id] : undefined;
  return Editor ? <Editor item={item} label={t(field.label)} /> : extension.field(field, item);
};

/** Its properties, but for those the layout places on their own. A reader
 *  sees none where it holds none; a community's own tool has none to offer. */
const ItemProperties = ({ item, view }: { item: DetailItem; view: LayoutContext }) => {
  const { home } = useDrawn();
  const placed = useContext(PlacedProperties);
  if (home.initiativeId === null) return null;
  if (home.readOnly && ownProperties(item.properties).every((each) => placed.has(each.property_id)))
    return null;
  return <PropertiesField {...propertiesOf(item, home, view)} except={placed} />;
};

/** What can be done with the item, at the end of the row it is in. A row too
 *  narrow for them beside the title puts them on a line of their own above it
 *  (the row's `stackClassName`). */
const ItemActions = () => {
  const { actions } = useDrawn().home;
  return actions ? (
    <div data-item-actions className="ml-auto shrink-0">
      {actions}
    </div>
  ) : null;
};

/** A part its layout requires, marked while it is empty for whoever can fill
 *  it in: as required while the item is being added, and as missing on an
 *  item that lacks it. */
const RequiredMark = ({
  node,
  item,
  children,
}: {
  node: LayoutNode;
  item: DetailItem;
  children: ReactNode;
}) => {
  const { t } = useTranslation("layouts");
  const { detail, home } = useDrawn();
  const draft = useContext(ItemDraftContext);
  const adding = draft !== null;
  const key = requiredKey(node);
  if (home.readOnly) return children;
  const missing = !(detail.filled?.(item, key, draft?.sent()) ?? true);
  // One frame whether or not it is filled, so filling it in keeps the editor
  // (and what is being typed in it) where it is.
  return (
    <div className="flex min-w-0 flex-col gap-1" data-required-missing={missing ? key : undefined}>
      {children}
      {missing ? (
        <p
          className={cn(
            "flex items-center gap-1 text-xs",
            adding ? "text-muted-foreground" : "text-destructive"
          )}
        >
          <CircleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {t(adding ? "required.label" : "required.missing")}
        </p>
      ) : null}
    </div>
  );
};

/** Each part drawn as `parts` draws it, marked where its layout requires it. */
const markRequired = <I,>(parts: Parts<I>): Parts<I> =>
  Object.fromEntries(
    Object.entries(parts).map(([type, draw]) => [
      type,
      (node: LayoutNode, item: I, view: LayoutContext, all: Parts<I>) =>
        isRequired(node) ? (
          <RequiredMark node={node} item={item as DetailItem}>
            {draw(node, item, view, all)}
          </RequiredMark>
        ) : (
          draw(node, item, view, all)
        ),
    ])
  );

/** The side of an item being added, folded until it is asked for. What is
 *  folded stays drawn, so a field keeps what it is holding. */
const MoreOptions = ({ children }: { children: ReactNode }) => {
  const { t } = useTranslation("layouts");
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="flex flex-col gap-4">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start text-muted-foreground"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
      >
        <ChevronDown
          className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
        {t("moreOptions")}
      </Button>
      <div id={id} hidden={!open} className="flex flex-col gap-4">
        {children}
      </div>
    </div>
  );
};

// A change of type changes how many parts come before the fold, so the fold is
// keyed by its type: it stays open, and what it holds stays drawn.
const drawChildren = <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) =>
  node.children?.map((child, index) => (
    <Fragment key={child.type === "more" ? "more" : index}>
      {renderNode(child, item, view, parts)}
    </Fragment>
  ));

/** What an item being added on one column is laid out with (`addingTree`). */
const ADDING_PARTS = {
  adding: <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
    <div className="flex min-w-0 flex-col gap-4">{drawChildren(node, item, view, parts)}</div>
  ),
  more: <I,>(node: LayoutNode, item: I, view: LayoutContext, parts: Parts<I>) => (
    <MoreOptions>{drawChildren(node, item, view, parts)}</MoreOptions>
  ),
};

/** The parts every item's detail has, then its extension's, then its kind's
 *  own. One being added draws what needs nothing saved: its fields and
 *  properties, its extension's parts, and the parts of its kind's own it
 *  names; nothing it could be done with yet. */
const partsOf = <I extends DetailItem>(
  added: Parts<I>,
  own: Parts<I> = {},
  adding?: readonly string[]
): Parts<I> => {
  const parts: Parts<I> = {
    ...LAYOUT_PARTS,
    field: (node: LayoutNode, item: I, view: LayoutContext) => (
      <ItemField id={String(node.props?.field)} item={item} view={view} />
    ),
    properties: (_node: LayoutNode, item: I, view: LayoutContext) => (
      <ItemProperties item={item} view={view} />
    ),
    actions: () => <ItemActions />,
    ...added,
    ...own,
  };
  if (!adding) return markRequired(parts);
  return {
    ...markRequired(
      Object.fromEntries(
        Object.entries(parts).filter(([type]) =>
          Object.hasOwn(own, type) ? adding.includes(type) : type !== "actions"
        )
      )
    ),
    ...ADDING_PARTS,
  };
};

type ViewProps<I extends DetailItem, C, P> = {
  detail: DetailKind<I, C, P>;
  item: I;
  context: C;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path, which
   *  the editor's detail tree shares. */
  editing?: boolean;
};

/**
 * An item's detail, drawn from its stored layout or as shipped, with what its
 * kind's extension adds drawn on it: what every item's page and the layout
 * editor's preview of it draw. Another item's detail starts afresh, with none
 * of this one's drafts.
 */
export const DetailLayoutView = <I extends DetailItem, C, P>(props: ViewProps<I, C, P>) => (
  <ItemDetail key={props.item.id} {...props} />
);

const ItemDetail = <I extends DetailItem, C, P>({
  detail,
  item,
  context,
  layout,
  editing,
}: ViewProps<I, C, P>) => {
  const home = detail.home(item, context);
  const { Shell } = detail;
  const spec = detail.typed?.spec(item) ?? detail.spec;
  const extension = detail.useExtension(home, spec.kind);
  const { env, fields: added, more, parts: addedParts } = extension;
  const adding = useContext(ItemDraftContext) !== null;
  const upFront = adding ? detail.addingUpFront : undefined;
  const tree = useMemo(() => {
    const laidOut = spec.tree(layout, more);
    return upFront ? addingTree(laidOut, [...upFront, ...requiredKeys(layout)]) : laidOut;
  }, [spec, layout, more, upFront]);
  const placed = useMemo(() => placedProperties(tree), [tree]);
  const view = useMemo<LayoutContext>(
    () => ({
      fields: detail.fields([], added),
      variant: "detail",
      env,
      editing: editing ? indexPaths(tree) : undefined,
    }),
    [detail, added, env, editing, tree]
  );
  const parts = useMemo(
    () => partsOf(addedParts, detail.parts, adding ? (detail.addingParts ?? []) : undefined),
    [addedParts, detail, adding]
  );
  // The parts every item has read the kind whatever its item is.
  const drawn = { detail, context, home, extension } as unknown as Drawn;
  const body = (
    <PlacedProperties.Provider value={placed}>
      {renderNode(tree, item, view, parts)}
    </PlacedProperties.Provider>
  );
  return (
    <DrawnItem.Provider value={drawn}>
      {extension.wrap(tree, Shell ? <Shell context={context}>{body}</Shell> : body)}
    </DrawnItem.Provider>
  );
};
