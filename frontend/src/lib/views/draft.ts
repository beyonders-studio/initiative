/**
 * The view editor's changes, kept apart from what is saved: a tree (a card or
 * an item's page) edited by path, and the draft with every change since it was
 * opened, to undo and redo.
 */

import type { CardPartInput, ViewDefinitionInput } from "@/api/generated/initiativeAPI.schemas";

import type { FieldDef } from "./fields";
import { TASK_CARD, TASK_COLUMNS } from "./tasks";
import type { ViewNode } from "./tree";

/** A view's card: its own, or the shipped one. */
export const cardOf = (definition: ViewDefinitionInput): ViewNode =>
  (definition.card as ViewNode | null | undefined) ?? TASK_CARD;

export const withCard = (definition: ViewDefinitionInput, card: ViewNode): ViewDefinitionInput => ({
  ...definition,
  card: card as CardPartInput,
});

/** A view's table columns, as field ids in order: its own, or the shipped ones. */
export const columnsOf = (definition: ViewDefinitionInput): string[] =>
  definition.columns ?? TASK_COLUMNS;

/** Where a node is in a tree: the child it is at each level below the root. */
export type NodePath = readonly number[];

/** Where a part is put: among the children of the node at `parent`, at
 *  `index`. A table's column is put at `index` among its columns. */
export type Place = { parent: NodePath; index: number };

/** A path as a key, the root's being "". */
export const pathKey = (path: NodePath): string => path.join(".");

export const pathOf = (key: string): NodePath => (key === "" ? [] : key.split(".").map(Number));

export const nodeAt = (root: ViewNode, path: NodePath): ViewNode | undefined =>
  path.reduce<ViewNode | undefined>((node, index) => node?.children?.[index], root);

/** `root` with the node at `path` changed by `change`, or taken out where it
 *  answers null. Every node off the path is the one it was. */
export const changeAt = (
  root: ViewNode,
  path: NodePath,
  change: (node: ViewNode) => ViewNode | null
): ViewNode => {
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
  root: ViewNode,
  parent: NodePath,
  node: ViewNode,
  index?: number
): ViewNode =>
  changeAt(root, parent, (holder) => {
    const children = [...(holder.children ?? [])];
    children.splice(index ?? children.length, 0, node);
    return { ...holder, children };
  });

/** `root` with the node at `from` moved to `to`, a path in the tree as it is
 *  after the move. */
export const moveNode = (root: ViewNode, from: NodePath, to: NodePath): ViewNode => {
  const node = nodeAt(root, from);
  if (!node || from.length === 0 || to.length === 0) return root;
  return insertAt(
    changeAt(root, from, () => null),
    to.slice(0, -1),
    node,
    to.at(-1)
  );
};

const nodesIn = (node: ViewNode): ViewNode[] => [node, ...(node.children ?? []).flatMap(nodesIn)];

/** Whether a part can be taken off the card: not one that is, or holds, a
 *  field every card shows (its title, which opens the task). */
export const removable = (node: ViewNode, fields: ReadonlyMap<string, FieldDef>): boolean =>
  !nodesIn(node).some(
    (each) => each.type === "field" && fields.get(String(each.props?.field))?.hideable === false
  );

/** The built-in fields a table draws as a column. */
const TABLE_BUILTINS = new Set(TASK_COLUMNS);

/** The fields a view can still add: a card's not on it (and no property alone
 *  where it shows them all), a table's not among its columns and drawn as
 *  one. */
export const addableFields = (
  definition: ViewDefinitionInput,
  fields: ReadonlyMap<string, FieldDef>
): FieldDef[] => {
  const all = [...fields.values()];
  if (definition.layout.type === "board") {
    const card = cardOf(definition);
    const named = namedFields(card);
    const showsProperties = holdsPart(card, "properties");
    return all.filter(
      (field) => !named.has(field.id) && !(showsProperties && field.source === "property")
    );
  }
  if (definition.layout.type === "table") {
    const columns = new Set(columnsOf(definition));
    return all.filter(
      (field) =>
        !columns.has(field.id) && (field.source !== "builtin" || TABLE_BUILTINS.has(field.id))
    );
  }
  return [];
};

/** What the editor has selected: the view (or page) itself, a part of its
 *  tree by path, or one of its table's columns by field. */
export type Selection =
  | { kind: "view" }
  | { kind: "part"; path: NodePath }
  | { kind: "column"; field: string };

export const VIEW_SELECTED: Selection = { kind: "view" };

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
export const dropInto = (root: ViewNode, from: NodePath, holder: NodePath): NodePath | null =>
  dropAt(from, holder, nodeAt(root, holder)?.children?.length ?? 0);

/** The parts that hold others, where a part can be added or dropped. */
export const HOLDERS = new Set(["card", "stack", "section", "header", "main", "side"]);

/** How long a view's name or a section's title may be, as the server allows. */
export const MAX_NAME_LENGTH = 100;

/** How many views a project may have, as the server allows. */
export const MAX_VIEWS = 40;

/** How many parts of one install a tree may place, as the server allows. */
export const MAX_PLUGIN_PARTS = 3;

/** The parts of an install a tree can still place: each once, and none past
 *  {@link MAX_PLUGIN_PARTS}. */
export const addablePluginParts = <P extends { id: string }>(
  tree: ViewNode,
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
export const holdsPart = (tree: ViewNode, type: string): boolean =>
  nodesIn(tree).some((node) => node.type === type);

/** The fields a tree names. */
export const namedFields = (tree: ViewNode): Set<string> =>
  new Set(
    nodesIn(tree).flatMap((node) => (node.type === "field" ? [String(node.props?.field)] : []))
  );

/** Every node of a tree by its path key, for the canvas to find the part a
 *  click landed on. Keyed by the node itself, so a tree drawn twice (a card
 *  on every task) names each part once. */
export const indexPaths = (root: ViewNode): WeakMap<ViewNode, string> => {
  const paths = new WeakMap<ViewNode, string>();
  const walk = (node: ViewNode, path: number[]) => {
    paths.set(node, pathKey(path));
    node.children?.forEach((child, index) => walk(child, [...path, index]));
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
