/**
 * The layout editor's changes, kept apart from what is saved: a tree (a card or
 * a detail) edited by path, and the draft with every change since it was
 * opened, to undo and redo.
 */

import type {
  CardPartInput,
  ListLayoutDefinitionInput,
  ListLayoutReadKind,
} from "@/api/generated/initiativeAPI.schemas";

import type { FieldDef } from "./fields";
import { MAX_PLUGIN_PARTS } from "./plugins";
import { TASK_CARD, TASK_COLUMNS } from "./tasks";
import type { LayoutNode } from "./tree";

/** What a target's lists draw until they are changed: a card's parts and a
 *  table's columns, and the built-in fields a table can draw as a column. */
export type ListShape = {
  card: LayoutNode;
  columns: readonly string[];
  columnFields: ReadonlySet<string>;
};

/** A project's lists, of its tasks. */
export const TASK_LIST_SHAPE: ListShape = {
  card: TASK_CARD,
  columns: TASK_COLUMNS,
  columnFields: new Set(TASK_COLUMNS),
};

/** The lists that draw each item as a card: a project's board, and a
 *  collection's walls of files. */
export const CARD_LISTS: ReadonlySet<ListLayoutReadKind> = new Set([
  "board",
  "masonry",
  "grid",
  "timeline",
]);

/** A list layout as the editor changes it: which list it is, how it draws what
 *  it lists, and what it draws as shipped where that is not a project's. */
export type ListLayout = {
  kind: ListLayoutReadKind;
  definition: ListLayoutDefinitionInput;
  shape?: ListShape;
};

/** The fields of the plug-ins placed on the tasks, which a list as shipped
 *  shows after its own: a plug-in shows as it arrives. */
const pluginFieldIds = (fields: ReadonlyMap<string, FieldDef>): string[] =>
  [...fields.values()].filter((field) => field.source === "plugin").map((field) => field.id);

/** A board's card: its own, or the shipped one with the plug-ins' fields. */
export const cardOf = (
  definition: ListLayoutDefinitionInput,
  fields: ReadonlyMap<string, FieldDef>,
  { card: shipped }: ListShape = TASK_LIST_SHAPE
): LayoutNode => {
  const own = definition.card as LayoutNode | null | undefined;
  if (own) return own;
  const plugins = pluginFieldIds(fields);
  return plugins.length === 0
    ? shipped
    : {
        ...shipped,
        children: [
          ...(shipped.children ?? []),
          ...plugins.map((field): LayoutNode => ({ type: "field", props: { field } })),
        ],
      };
};

export const withCard = (
  definition: ListLayoutDefinitionInput,
  card: LayoutNode
): ListLayoutDefinitionInput => ({ ...definition, card: card as CardPartInput });

/** A table's columns, as field ids in order: its own, or the shipped ones
 *  with the plug-ins' fields. */
export const columnsOf = (
  definition: ListLayoutDefinitionInput,
  fields: ReadonlyMap<string, FieldDef>,
  { columns: shipped }: ListShape = TASK_LIST_SHAPE
): string[] => definition.columns ?? [...shipped, ...pluginFieldIds(fields)];

/** Where a node is in a tree: the child it is at each level below the root. */
export type NodePath = readonly number[];

/** Where a part is put: among the children of the node at `parent`, at
 *  `index`. A table's column is put at `index` among its columns. */
export type Place = { parent: NodePath; index: number };

/** A path as a key, the root's being "". */
export const pathKey = (path: NodePath): string => path.join(".");

export const pathOf = (key: string): NodePath => (key === "" ? [] : key.split(".").map(Number));

export const nodeAt = (root: LayoutNode, path: NodePath): LayoutNode | undefined =>
  path.reduce<LayoutNode | undefined>((node, index) => node?.children?.[index], root);

/** `root` with the node at `path` changed by `change`, or taken out where it
 *  answers null. Every node off the path is the one it was. */
export const changeAt = (
  root: LayoutNode,
  path: NodePath,
  change: (node: LayoutNode) => LayoutNode | null
): LayoutNode => {
  if (path.length === 0) return change(root) ?? root;
  const [index, ...rest] = path;
  const children = [...(root.children ?? [])];
  const child = children[index];
  if (!child) return root;
  const changed = rest.length === 0 ? change(child) : changeAt(child, rest, change);
  if (changed === null) children.splice(index, 1);
  else children[index] = changed;
  return { ...root, children };
};

/** `root` with `node` among the children of the node at `parent`, at `index`
 *  or last. */
export const insertAt = (
  root: LayoutNode,
  parent: NodePath,
  node: LayoutNode,
  index?: number
): LayoutNode =>
  changeAt(root, parent, (holder) => {
    const children = [...(holder.children ?? [])];
    children.splice(index ?? children.length, 0, node);
    return { ...holder, children };
  });

/** `root` with the node at `from` moved to `to`, a path in the tree as it is
 *  after the move. */
export const moveNode = (root: LayoutNode, from: NodePath, to: NodePath): LayoutNode => {
  const node = nodeAt(root, from);
  if (!node || from.length === 0 || to.length === 0) return root;
  return insertAt(
    changeAt(root, from, () => null),
    to.slice(0, -1),
    node,
    to.at(-1)
  );
};

const nodesIn = (node: LayoutNode): LayoutNode[] => [
  node,
  ...(node.children ?? []).flatMap(nodesIn),
];

/** Whether a part can be taken off the card: not one that is, or holds, a
 *  field every card shows (its title, which opens the task). */
export const removable = (node: LayoutNode, fields: ReadonlyMap<string, FieldDef>): boolean =>
  !nodesIn(node).some(
    (each) => each.type === "field" && fields.get(String(each.props?.field))?.hideable === false
  );

/** Whether a detail's layout can require a part: a field a person fills in,
 *  or one of the detail's own parts that edits one (`requiredParts`). A
 *  detail that requires nothing (`null`) requires none of them. */
export const canRequire = (
  node: LayoutNode,
  fields: ReadonlyMap<string, FieldDef>,
  requiredParts: ReadonlySet<string> | null
): boolean =>
  requiredParts !== null &&
  (node.type === "field"
    ? fields.get(String(node.props?.field))?.requireable === true
    : requiredParts.has(node.type));

/** The fields a list layout can still add: a card's not on it (and no
 *  property alone where it shows them all), a table's not among its columns
 *  and drawn as one. */
export const addableFields = (
  { kind, definition, shape = TASK_LIST_SHAPE }: ListLayout,
  fields: ReadonlyMap<string, FieldDef>
): FieldDef[] => {
  const all = [...fields.values()];
  if (CARD_LISTS.has(kind)) {
    const card = cardOf(definition, fields, shape);
    const named = namedFields(card);
    const showsProperties = holdsPart(card, "properties");
    return all.filter(
      (field) => !named.has(field.id) && !(showsProperties && field.source === "property")
    );
  }
  if (kind === "table") {
    const columns = new Set(columnsOf(definition, fields, shape));
    return all.filter(
      (field) =>
        !columns.has(field.id) && (field.source !== "builtin" || shape.columnFields.has(field.id))
    );
  }
  return [];
};

/** What the editor has selected: the layout itself, a part of its tree by
 *  path, or one of its table's columns by field. */
export type Selection =
  | { kind: "layout" }
  | { kind: "part"; path: NodePath }
  | { kind: "column"; field: string };

export const LAYOUT_SELECTED: Selection = { kind: "layout" };

export const sameSelection = (a: Selection, b: Selection): boolean =>
  a.kind === b.kind &&
  (a.kind !== "part" || pathKey(a.path) === pathKey((b as { path: NodePath }).path)) &&
  (a.kind !== "column" || a.field === (b as { field: string }).field);

const startsWith = (path: NodePath, prefix: NodePath) =>
  prefix.length <= path.length && prefix.every((index, depth) => path[depth] === index);

/** Where the part at `path` is once the part at `removed` is taken out, or
 *  null when it went with it. */
export const pathAfterRemove = (path: NodePath, removed: NodePath): NodePath | null => {
  if (startsWith(path, removed)) return null;
  const depth = removed.length - 1;
  if (path.length <= depth || !startsWith(path, removed.slice(0, depth))) return path;
  if (path[depth] < removed[depth]) return path;
  return [...path.slice(0, depth), path[depth] - 1, ...path.slice(depth + 1)];
};

/** Where the part at `path` is once a part is put in at `inserted`. */
const pathAfterInsert = (path: NodePath, inserted: NodePath): NodePath => {
  const depth = inserted.length - 1;
  if (path.length <= depth || !startsWith(path, inserted.slice(0, depth))) return path;
  if (path[depth] < inserted[depth]) return path;
  return [...path.slice(0, depth), path[depth] + 1, ...path.slice(depth + 1)];
};

/** Where the part at `path` is once the part at `from` moves to `to`: the
 *  moved part, and what it holds, go with it; the rest close up and make
 *  room. */
export const pathAfterMove = (path: NodePath, from: NodePath, to: NodePath): NodePath =>
  startsWith(path, from)
    ? [...to, ...path.slice(from.length)]
    : pathAfterInsert(pathAfterRemove(path, from) ?? path, to);

/** Where the part at `from` goes when it is dropped on the part at `over`:
 *  into its place, as a list reorders, or null where that would put it inside
 *  itself. */
export const dropOn = (from: NodePath, over: NodePath): NodePath | null => {
  if (startsWith(over, from)) return null;
  const siblings = over.length === from.length && startsWith(over, from.slice(0, -1));
  // Among its own siblings it takes the place it was dropped on; elsewhere it
  // goes in before what it was dropped on.
  return siblings ? over : (pathAfterRemove(over, from) as NodePath);
};

/** Where the part at `from` goes when it is put at `index` among the children
 *  of `holder` (both read before the move), or null where that would put it
 *  inside itself. */
export const dropAt = (from: NodePath, holder: NodePath, index: number): NodePath | null => {
  if (startsWith(holder, from)) return null;
  // Taken from before the place, it leaves one fewer ahead of it.
  const ahead =
    from.length === holder.length + 1 && startsWith(from, holder) && (from.at(-1) ?? 0) < index;
  return [...(pathAfterRemove(holder, from) as NodePath), ahead ? index - 1 : index];
};

/** Where the part at `from` goes when it is dropped at the end of the group
 *  at `holder`, or null where that would put it inside itself. */
export const dropInto = (root: LayoutNode, from: NodePath, holder: NodePath): NodePath | null =>
  dropAt(from, holder, nodeAt(root, holder)?.children?.length ?? 0);

/** The parts that hold others, where a part can be added or dropped. */
export const HOLDERS = new Set(["card", "stack", "section", "header", "main", "side"]);

/** How long a section's title may be, as the server allows. */
export const MAX_TITLE_LENGTH = 100;

/** The parts of an install a tree can still place: each once, and none past
 *  {@link MAX_PLUGIN_PARTS}. */
export const addablePluginParts = <P extends { id: string }>(
  tree: LayoutNode,
  install: number,
  parts: P[]
): P[] => {
  const placed = nodesIn(tree).flatMap((node) =>
    node.type === "plugin" && Number(node.props?.plugin) === install
      ? [String(node.props?.part)]
      : []
  );
  return placed.length >= MAX_PLUGIN_PARTS ? [] : parts.filter((part) => !placed.includes(part.id));
};

/** Whether a tree holds a part of the type. */
export const holdsPart = (tree: LayoutNode, type: string): boolean =>
  nodesIn(tree).some((node) => node.type === type);

/** The fields a tree names. */
export const namedFields = (tree: LayoutNode): Set<string> =>
  new Set(
    nodesIn(tree).flatMap((node) => (node.type === "field" ? [String(node.props?.field)] : []))
  );

/** Every node of a tree by its path key, for the canvas to find the part a
 *  click landed on. Keyed by the node itself, so a tree drawn twice (a card
 *  on every task) names each part once. */
export const indexPaths = (root: LayoutNode): WeakMap<LayoutNode, string> => {
  const paths = new WeakMap<LayoutNode, string>();
  const walk = (node: LayoutNode, path: number[]) => {
    paths.set(node, pathKey(path));
    node.children?.forEach((child, index) => {
      walk(child, [...path, index]);
    });
  };
  walk(root, []);
  return paths;
};

/** A draft being edited, with what was done to it. */
export type History<T> = {
  past: T[];
  present: T;
  future: T[];
};

export type HistoryAction<T> =
  | { type: "change"; present: T }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; present: T };

export const startHistory = <T>(present: T): History<T> => ({
  past: [],
  present,
  future: [],
});

export const historyReducer = <T>(history: History<T>, action: HistoryAction<T>): History<T> => {
  switch (action.type) {
    case "change":
      return { past: [...history.past, history.present], present: action.present, future: [] };
    case "undo": {
      const previous = history.past.at(-1);
      if (!previous) return history;
      return {
        past: history.past.slice(0, -1),
        present: previous,
        future: [history.present, ...history.future],
      };
    }
    case "redo": {
      const [next, ...future] = history.future;
      if (!next) return history;
      return { past: [...history.past, history.present], present: next, future };
    }
    case "reset":
      return startHistory(action.present);
  }
};
