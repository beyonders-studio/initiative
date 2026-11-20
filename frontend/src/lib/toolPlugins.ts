/**
 * The tools a community's tool plug-ins declare, read off each install's
 * pinned definition.
 *
 * A tool plug-in runs no code: its `tool` block declares a tool (its key,
 * names and icon, the fields of its rows, the item tables under them, their
 * layouts and actions), and Initiative serves it as it serves its own. Every
 * table of it, the tool's own and each item's, is a kind: its key, `.` and the
 * plug-in's uid in lower case, which no built-in kind can be.
 *
 * Nothing here names one tool. Publishing checked each declaration against the
 * contract, so this reads it as the contract writes it.
 */

import { type LucideIcon, type LucideProps, Puzzle } from "lucide-react";
import { createElement, forwardRef, useEffect, useState } from "react";

import {
  type CommunityPluginListResponse,
  type CommunityPluginRead,
  CounterLook,
  type CurrencyCode,
  type DetailLayoutDefinitionInput,
  type GetLayoutsParams,
  type MetadataType,
  type PluginToolRowRead,
  type PluginToolRowUpdate,
  type PluginToolRowUpdateFields,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { initiativeRoute } from "@/lib/tools";
import type { ListLayoutDefinition } from "@/ui/layouts/layoutSet";
import { type LocalizedText, localized } from "@/ui/lib/localized";

/**
 * The icons a tool plug-in may name (the contract's `toolIcon`), each the
 * app's own, loaded the first time one is drawn. `toolPlugins.test.ts` holds
 * this to the contract's list, so a name the SDK allows always draws.
 */
export const TOOL_PLUGIN_ICONS: Readonly<Record<string, () => Promise<{ default: LucideIcon }>>> = {
  beaker: () => import("lucide-react/icons/beaker"),
  book: () => import("lucide-react/icons/book"),
  bookmark: () => import("lucide-react/icons/bookmark"),
  box: () => import("lucide-react/icons/box"),
  briefcase: () => import("lucide-react/icons/briefcase"),
  calendar: () => import("lucide-react/icons/calendar"),
  camera: () => import("lucide-react/icons/camera"),
  "chart-bar": () => import("lucide-react/icons/chart-bar"),
  "chart-line": () => import("lucide-react/icons/chart-line"),
  "chart-pie": () => import("lucide-react/icons/chart-pie"),
  "clipboard-list": () => import("lucide-react/icons/clipboard-list"),
  clock: () => import("lucide-react/icons/clock"),
  "dice-5": () => import("lucide-react/icons/dice-5"),
  "file-text": () => import("lucide-react/icons/file-text"),
  flag: () => import("lucide-react/icons/flag"),
  "flask-conical": () => import("lucide-react/icons/flask-conical"),
  folder: () => import("lucide-react/icons/folder"),
  gauge: () => import("lucide-react/icons/gauge"),
  gift: () => import("lucide-react/icons/gift"),
  hammer: () => import("lucide-react/icons/hammer"),
  heart: () => import("lucide-react/icons/heart"),
  hourglass: () => import("lucide-react/icons/hourglass"),
  image: () => import("lucide-react/icons/image"),
  inbox: () => import("lucide-react/icons/inbox"),
  kanban: () => import("lucide-react/icons/kanban"),
  layers: () => import("lucide-react/icons/layers"),
  leaf: () => import("lucide-react/icons/leaf"),
  lightbulb: () => import("lucide-react/icons/lightbulb"),
  list: () => import("lucide-react/icons/list"),
  "list-checks": () => import("lucide-react/icons/list-checks"),
  map: () => import("lucide-react/icons/map"),
  "map-pin": () => import("lucide-react/icons/map-pin"),
  "message-square": () => import("lucide-react/icons/message-square"),
  notebook: () => import("lucide-react/icons/notebook"),
  package: () => import("lucide-react/icons/package"),
  palette: () => import("lucide-react/icons/palette"),
  puzzle: () => import("lucide-react/icons/puzzle"),
  receipt: () => import("lucide-react/icons/receipt"),
  shield: () => import("lucide-react/icons/shield"),
  "shopping-cart": () => import("lucide-react/icons/shopping-cart"),
  star: () => import("lucide-react/icons/star"),
  table: () => import("lucide-react/icons/table"),
  tag: () => import("lucide-react/icons/tag"),
  target: () => import("lucide-react/icons/target"),
  timer: () => import("lucide-react/icons/timer"),
  trophy: () => import("lucide-react/icons/trophy"),
  user: () => import("lucide-react/icons/user"),
  users: () => import("lucide-react/icons/users"),
  wallet: () => import("lucide-react/icons/wallet"),
  wrench: () => import("lucide-react/icons/wrench"),
};

const loadedIcons = new Map<string, LucideIcon>();
const toolIcons = new Map<string, LucideIcon>();

/** A tool's icon by the name it declares, drawn once it has loaded (taking
 *  its room until then), or the puzzle piece for a name the app does not
 *  have. One component per name, so a redraw keeps it. */
export const toolPluginIcon = (name: string): LucideIcon => {
  const load = TOOL_PLUGIN_ICONS[name];
  if (!load) return Puzzle;
  const known = toolIcons.get(name);
  if (known) return known;
  const icon = forwardRef<SVGSVGElement, LucideProps>((props, ref) => {
    const [Loaded, setLoaded] = useState(() => loadedIcons.get(name));
    useEffect(() => {
      if (Loaded) return;
      let live = true;
      void load().then(({ default: drawn }) => {
        loadedIcons.set(name, drawn);
        if (live) setLoaded(() => drawn);
      });
      return () => {
        live = false;
      };
    }, [Loaded]);
    return Loaded
      ? createElement(Loaded, { ...props, ref })
      : createElement("span", { className: props.className, "aria-hidden": true });
  }) as LucideIcon;
  icon.displayName = `ToolIcon(${name})`;
  toolIcons.set(name, icon);
  return icon;
};

/** The kinds of field a tool's rows hold (the contract's `toolFieldKind`). */
export type ToolFieldKind =
  | "text"
  | "number"
  | "date"
  | "datetime"
  | "checkbox"
  | "url"
  | "currency"
  | "select"
  | "multi_select"
  | "user_reference"
  | "scale"
  | "counter"
  | "color";

/** A counter's bound: a number, or the key of a number field of its row. */
export type ToolBound = number | string;

/** One field of a table, as declared. */
export interface ToolFieldDecl {
  key: string;
  name: LocalizedText;
  kind: ToolFieldKind;
  options?: { value: string; label: LocalizedText; color?: string }[];
  currency?: CurrencyCode;
  default?: unknown;
  counter?: { min?: ToolBound; max?: ToolBound; step?: ToolBound; initial?: ToolBound };
}

/** One way a table's rows are listed: a grid or a masonry wall of its card,
 *  or a table of its columns, with its looks and its presets. */
export type ToolListLayout = ListLayoutDefinition & { kind: "grid" | "masonry" | "table" };

/** What one table draws: the lists its rows are listed in, the first the one
 *  a person starts on, and one row's page. */
export interface ToolLayoutsDecl {
  lists: ToolListLayout[];
  detail: DetailLayoutDefinitionInput;
}

/** An action a reader runs on one row. */
export interface ToolActionDecl {
  id: string;
  name: LocalizedText;
  /** The key of the table whose rows it runs on. */
  on: string;
  /** The keys of the fields of its table the reader is asked for before it
   *  runs. */
  params?: string[];
  confirm?: LocalizedText;
}

interface ToolItemDecl {
  key: string;
  name: LocalizedText;
  parent?: string;
  fields: ToolFieldDecl[];
  layouts: ToolLayoutsDecl;
}

/** A definition's `tool` block. */
interface ToolDecl {
  key: string;
  name: LocalizedText;
  instance_name: LocalizedText;
  icon: string;
  fields?: ToolFieldDecl[];
  layouts: ToolLayoutsDecl;
  items?: ToolItemDecl[];
  actions?: ToolActionDecl[];
}

/** One table of an installed tool: the tool's own, or an item table. */
export interface ToolTable {
  kind: string;
  /** What one of its rows is called. */
  name: LocalizedText;
  fields: ToolFieldDecl[];
  layouts: ToolLayoutsDecl;
  /** The kind of the table its rows sit under; null for the tool's own. */
  parent: string | null;
  /** The kinds of the item tables right under it, in declared order. */
  items: string[];
  /** The actions run on its rows. */
  actions: ToolActionDecl[];
}

/** A tool an installed plug-in declares. */
export interface InstalledTool {
  /** The tool's own kind. */
  kind: string;
  /** The install that declares it. */
  pluginId: number;
  /** The tool's name, which the sidebar shows. */
  name: LocalizedText;
  icon: LucideIcon;
  /** Every table of it by kind, the tool's own first. */
  tables: ReadonlyMap<string, ToolTable>;
}

/** A plug-in table's kind: its key, then `.` and the plug-in's uid in lower
 *  case. */
export const toolPluginKind = (key: string, listingUid: string): string =>
  `${key}.${listingUid.toLowerCase()}`;

/** How a plug-in table's kind is written: a key (a lower-case letter, then
 *  lower-case letters, digits and `_`), `.`, and a uid in lower case. */
const TOOL_PLUGIN_KIND = /^[a-z][a-z0-9_]*\.[a-z0-9]+$/;

/** Whether a kind is written as a plug-in's: built-in kinds never hold a `.`. */
export const isToolPluginKind = (kind: string): boolean => TOOL_PLUGIN_KIND.test(kind);

const isToolDecl = (definition: Record<string, unknown>): boolean =>
  definition.plugin_kind === "tool" &&
  typeof definition.tool === "object" &&
  definition.tool !== null;

/** The tool one install declares, or null for a plug-in of another kind. */
export const installedTool = (
  plugin: Pick<CommunityPluginRead, "id" | "listing_uid" | "definition">
): InstalledTool | null => {
  const definition = plugin.definition as Record<string, unknown>;
  if (!isToolDecl(definition)) return null;
  const tool = definition.tool as ToolDecl;
  const kindOf = (key: string) => toolPluginKind(key, plugin.listing_uid);
  const items = tool.items ?? [];
  const actions = tool.actions ?? [];
  const table = (
    key: string,
    name: LocalizedText,
    fields: ToolFieldDecl[],
    layouts: ToolLayoutsDecl,
    parent: string | null
  ): [string, ToolTable] => [
    kindOf(key),
    {
      kind: kindOf(key),
      name,
      fields,
      layouts,
      parent: parent === null ? null : kindOf(parent),
      items: items
        .filter((item) => (item.parent ?? tool.key) === key)
        .map((item) => kindOf(item.key)),
      actions: actions.filter((action) => action.on === key),
    },
  ];
  return {
    kind: kindOf(tool.key),
    pluginId: plugin.id,
    name: tool.name,
    icon: toolPluginIcon(tool.icon),
    tables: new Map([
      table(tool.key, tool.instance_name, tool.fields ?? [], tool.layouts, null),
      ...items.map((item) =>
        table(item.key, item.name, item.fields, item.layouts, item.parent ?? tool.key)
      ),
    ]),
  };
};

/** The tools a community's installs declare that are on and reachable, in
 *  the order they were installed. */
export const installedTools = (
  plugins: readonly Pick<
    CommunityPluginRead,
    "id" | "listing_uid" | "definition" | "enabled" | "available"
  >[]
): InstalledTool[] =>
  plugins
    .filter((plugin) => plugin.enabled && plugin.available !== false)
    .flatMap((plugin) => installedTool(plugin) ?? []);

/** What `useCommunityPlugins` selects for the installed tools. */
export const selectInstalledTools = (data: Pick<CommunityPluginListResponse, "items">) =>
  installedTools(data.items);

/** The installed tool a kind belongs to, the tool's own or an item's, and its
 *  table; null for a kind none of them has. */
export const toolOfKind = (
  tools: readonly InstalledTool[],
  kind: string
): { tool: InstalledTool; table: ToolTable } | null => {
  for (const tool of tools) {
    const table = tool.tables.get(kind);
    if (table) return { tool, table };
  }
  return null;
};

/** Localized text in the reader's language. */
export const toolText = (text: LocalizedText, language: string): string =>
  localized(text, language) ?? "";

// --- Routes -----------------------------------------------------------------
// One route tree for every tool plug-in, community-relative like every tool
// route: a tool's list in an initiative, and any row of it, the tool's own or
// an item's, by its kind.

/** e.g. "/i/12/t/board.abc123". */
export const toolPluginListRoute = (initiativeId: number, kind: string): string =>
  `${initiativeRoute(initiativeId)}/t/${kind}`;

/** e.g. "/i/12/t/card.abc123/7". */
export const toolPluginRowRoute = (initiativeId: number, kind: string, id: number): string =>
  `${toolPluginListRoute(initiativeId, kind)}/${id}`;

/** Where a table's layouts are edited: the tool's own rows' in the
 *  initiative ("/i/12/t/board.abc123/layouts"), an item table's under the row
 *  its items sit in ("/i/12/t/card.abc123/layouts/7"). */
export const toolPluginLayoutsRoute = (
  initiativeId: number,
  kind: string,
  under: number | null
): string =>
  `${toolPluginListRoute(initiativeId, kind)}/layouts${under === null ? "" : `/${under}`}`;

// --- Layouts ----------------------------------------------------------------
// A table is laid out in each place its rows are listed: the tool's own rows
// in their initiative, as a tool the initiative shares is, and an item
// table's rows under the row they sit in, as an instance of a tool is.

/** The layouts of a table's rows where they are listed: in `initiativeId`
 *  for the tool's own, under the row `parentId` for an item's. */
export const toolLayoutTarget = (
  kind: string,
  initiativeId: number,
  parentId: number | null
): GetLayoutsParams =>
  parentId === null
    ? { tool: kind, initiative_id: initiativeId }
    : { tool: kind, tool_id: parentId };

// --- Rows -------------------------------------------------------------------

/** A row of a plug-in's table, the tool's own or an item's, as the kit draws
 *  an item. Its rows hold none of the initiative's properties. */
export type ToolRow = PluginToolRowRead & { properties: PropertySummary[] };

/** A row as read, drawn as an item. */
export const toolRow = (read: PluginToolRowRead): ToolRow => ({ ...read, properties: [] });

/** What a row holds for one of its declared fields: a person by id, any other
 *  kind as its value. */
export const fieldValue = (row: PluginToolRowRead, field: ToolFieldDecl): unknown =>
  (field.kind === "user_reference" ? row.people[field.key] : row.fields[field.key]) ?? null;

/** What a declared field of a table holds where nobody wrote it, as the
 *  server starts it (`effective_defaults`): its default, false for a
 *  checkbox, nothing otherwise. A counter starts at its `initial`, the number
 *  or the start of the field it names, else 0; a colour the server picks at
 *  random is none yet. */
export const fieldStart = (fields: readonly ToolFieldDecl[], field: ToolFieldDecl): unknown => {
  if (field.kind === "counter") {
    const initial = field.counter?.initial;
    if (typeof initial !== "string") return initial ?? 0;
    const named = fields.find((each) => each.key === initial && each.kind !== "counter");
    return (named ? fieldStart(fields, named) : null) ?? 0;
  }
  if (field.kind === "color" && field.default === "random") return null;
  return field.default ?? (field.kind === "checkbox" ? false : null);
};

/** One field's value as a change sends it: a person among its people, any
 *  other kind among its fields. */
export const fieldChange = (
  field: ToolFieldDecl,
  value: unknown
): Pick<PluginToolRowUpdate, "fields" | "people"> =>
  field.kind === "user_reference"
    ? { people: { [field.key]: value as number | null } }
    : { fields: { [field.key]: value as PluginToolRowUpdateFields[string] } };

/** Several fields' values as a change sends them, each as `fieldChange`
 *  puts it. */
export const fieldChanges = (
  values: readonly (readonly [ToolFieldDecl, unknown])[]
): Required<Pick<PluginToolRowUpdate, "fields" | "people">> => {
  const changes = values.map(([field, value]) => fieldChange(field, value));
  return {
    fields: Object.assign({}, ...changes.map((change) => change.fields)),
    people: Object.assign({}, ...changes.map((change) => change.people)),
  };
};

/** `row` holding the values `change` sends. */
export const withChange = <R extends Pick<PluginToolRowRead, "fields" | "people">>(
  row: R,
  change: Pick<PluginToolRowUpdate, "fields" | "people">
): R => ({
  ...row,
  fields: { ...row.fields, ...change.fields },
  people: { ...row.people, ...change.people },
});

/** A counter's bound as one row holds it: the number given, or the value of
 *  the field it names. */
const boundOf = (row: PluginToolRowRead, bound: ToolBound | undefined): number | null => {
  if (bound === undefined) return null;
  if (typeof bound === "number") return bound;
  const value = row.fields[bound];
  return value === null || value === undefined || value === "" ? null : Number(value);
};

/**
 * One of a row's declared fields as the kit draws a property's value: its
 * kind, its options in the reader's language, and a counter's bounds as this
 * row holds them. A colour is drawn on its own (`toolFields`), never as a
 * property.
 */
export const fieldSummary = (
  field: ToolFieldDecl,
  row: PluginToolRowRead,
  language: string
): PropertySummary => ({
  property_id: 0,
  name: toolText(field.name, language),
  type: field.kind as MetadataType,
  project_id: null,
  collection_id: null,
  install_id: null,
  key: field.key,
  options:
    field.options?.map((option) => ({
      value: option.value,
      label: toolText(option.label, language),
      color: option.color ?? null,
    })) ?? null,
  currency: field.currency ?? null,
  counter:
    field.kind === "counter"
      ? {
          min: boundOf(row, field.counter?.min),
          max: boundOf(row, field.counter?.max),
          step: boundOf(row, field.counter?.step) ?? 1,
          initial: boundOf(row, field.counter?.initial) ?? 0,
          look: CounterLook.number,
        }
      : null,
  value: fieldValue(row, field),
});
