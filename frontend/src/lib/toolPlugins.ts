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

import {
  Beaker,
  Book,
  Bookmark,
  Box,
  Briefcase,
  Calendar,
  Camera,
  ChartBar,
  ChartLine,
  ChartPie,
  ClipboardList,
  Clock,
  Dice5,
  FileText,
  Flag,
  FlaskConical,
  Folder,
  Gauge,
  Gift,
  Hammer,
  Heart,
  Hourglass,
  Image,
  Inbox,
  Kanban,
  Layers,
  Leaf,
  Lightbulb,
  List,
  ListChecks,
  type LucideIcon,
  Map as MapIcon,
  MapPin,
  MessageSquare,
  Notebook,
  Package,
  Palette,
  Puzzle,
  Receipt,
  Shield,
  ShoppingCart,
  Star,
  Table,
  Tag,
  Target,
  Timer,
  Trophy,
  User,
  Users,
  Wallet,
  Wrench,
} from "lucide-react";

import {
  type CommunityPluginRead,
  CounterLook,
  type CurrencyCode,
  type DetailLayoutDefinitionInput,
  type ListLayoutDefinitionInput,
  type MetadataType,
  type PluginToolRowRead,
  type PluginToolRowUpdate,
  type PluginToolRowUpdateFields,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import { initiativeRoute } from "@/lib/tools";
import { type LocalizedText, localized } from "@/lib/widgets/widgetMeta";

/**
 * The icons a tool plug-in may name (the contract's `toolIcon`), each the
 * app's own. `toolPlugins.test.ts` holds this to the contract's list, so a
 * name the SDK allows always draws.
 */
export const TOOL_PLUGIN_ICONS: Readonly<Record<string, LucideIcon>> = {
  beaker: Beaker,
  book: Book,
  bookmark: Bookmark,
  box: Box,
  briefcase: Briefcase,
  calendar: Calendar,
  camera: Camera,
  "chart-bar": ChartBar,
  "chart-line": ChartLine,
  "chart-pie": ChartPie,
  "clipboard-list": ClipboardList,
  clock: Clock,
  "dice-5": Dice5,
  "file-text": FileText,
  flag: Flag,
  "flask-conical": FlaskConical,
  folder: Folder,
  gauge: Gauge,
  gift: Gift,
  hammer: Hammer,
  heart: Heart,
  hourglass: Hourglass,
  image: Image,
  inbox: Inbox,
  kanban: Kanban,
  layers: Layers,
  leaf: Leaf,
  lightbulb: Lightbulb,
  list: List,
  "list-checks": ListChecks,
  map: MapIcon,
  "map-pin": MapPin,
  "message-square": MessageSquare,
  notebook: Notebook,
  package: Package,
  palette: Palette,
  puzzle: Puzzle,
  receipt: Receipt,
  shield: Shield,
  "shopping-cart": ShoppingCart,
  star: Star,
  table: Table,
  tag: Tag,
  target: Target,
  timer: Timer,
  trophy: Trophy,
  user: User,
  users: Users,
  wallet: Wallet,
  wrench: Wrench,
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

/** How a table's rows are listed: a grid of its card, or a table of its
 *  columns. */
export type ToolListLayout = { kind: "grid" | "table" } & Pick<
  ListLayoutDefinitionInput,
  "card" | "columns" | "displays"
>;

/** What one table draws: its list, and one row's page. */
export interface ToolLayoutsDecl {
  list: ToolListLayout;
  detail: DetailLayoutDefinitionInput;
}

/** An action a reader runs on one row. */
export interface ToolActionDecl {
  id: string;
  name: LocalizedText;
  /** The key of the table whose rows it runs on. */
  on: string;
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

/** Whether a kind is a plug-in's: built-in kinds never hold a `.`. */
export const isToolPluginKind = (kind: string): boolean => kind.includes(".");

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
    icon: TOOL_PLUGIN_ICONS[tool.icon] ?? Puzzle,
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

/** One field's value as a change sends it: a person among its people, any
 *  other kind among its fields. */
export const fieldChange = (
  field: ToolFieldDecl,
  value: unknown
): Pick<PluginToolRowUpdate, "fields" | "people"> =>
  field.kind === "user_reference"
    ? { people: { [field.key]: value as number | null } }
    : { fields: { [field.key]: value as PluginToolRowUpdateFields[string] } };

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
