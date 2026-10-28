import { Check, ExternalLink, Minus } from "lucide-react";
import {
  createContext,
  Fragment,
  type ReactNode,
  useContext,
  useId,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type CommunityPluginRead,
  type DetailLayoutReadKind,
  ItemKind,
  MetadataType,
  type PropertySummary,
} from "@/api/generated/initiativeAPI.schemas";
import type { PluginDataParam } from "@/api/pluginData";
import { PluginParamControl } from "@/components/plugins/PluginParamControl";
import type { PluginFilterField } from "@/components/properties/PropertyFilter";
import { PropertyValueCell, ScaleValue } from "@/components/properties/PropertyValueCell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import contract from "@/contract/manifest.contract.json";
import { useCommunityPlugins, useRunPluginAction } from "@/hooks/useCommunityPlugins";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import { numberFormat } from "@/lib/intl";
import { cn } from "@/lib/utils";
import { withParamAnswer } from "@/lib/widgets/pluginParams";
import { type LocalizedText, localized } from "@/lib/widgets/widgetMeta";

import type { FieldDef, FieldRendererProps } from "./fields";
import { Section } from "./section";

/** What a plug-in draws on an item from: the item, and the values it carries,
 *  a plug-in's among them by its install and key. */
export type PluginItem = { id: number; properties?: PropertySummary[] };

import type { LayoutNode } from "./tree";

// What an install's pinned definition declares for items, as the SDK's
// contract writes it (`fields`, `parts`, `actions`). Publishing checked it.

type Tone = "accent" | "positive" | "negative" | "warning" | "neutral" | "muted";

export type PluginFieldKind =
  | "text"
  | "number"
  | "date"
  | "datetime"
  | "link"
  | "badge"
  | "scale"
  | "checkbox"
  | "url"
  | "currency"
  | "select"
  | "multi_select"
  | "user_reference";

/** One facet of a field's state: the keys a value may name, each a badge. */
type StateFacet = {
  name: LocalizedText;
  values: Record<string, { label: LocalizedText; tone?: Tone }>;
};

export type PluginFieldDecl = {
  key: string;
  name: LocalizedText;
  kind: PluginFieldKind;
  on: string[];
  tone?: Tone;
  /** Several values rather than one: each an element with a `ref` of its own. */
  list?: boolean;
  /** The states a value may be in, by facet, drawn as badges beside it. */
  states?: Record<string, StateFacet>;
  /** On a list, the actions offered on each of its elements, by id. */
  actions?: string[];
};

export type PluginPartDecl = {
  id: string;
  name: LocalizedText;
  on: string[];
  tree: LayoutNode;
  description?: LocalizedText;
};

export type PluginActionDecl = {
  id: string;
  name: LocalizedText;
  on: string[];
  confirm?: LocalizedText;
  menu?: boolean;
  /** The endpoint the action calls, whose parameters it may ask for. */
  endpoint?: string;
  /** The endpoint's parameters the reader is asked for before it runs. */
  params?: string[];
};

/** One install as a reader meets it on one kind of item: what it declares
 *  there, of what the server offers this reader. */
export type PluginOnItems = {
  id: number;
  /** The kind of item it is met on. */
  kind: PluginItemKind;
  /** What the community calls the install. */
  name: string;
  fields: ReadonlyMap<string, PluginFieldDecl>;
  parts: ReadonlyMap<string, PluginPartDecl>;
  actions: ReadonlyMap<string, PluginActionDecl>;
  /** Each endpoint's declared parameters, by endpoint id: what an action's
   *  question is drawn from. */
  endpoints: ReadonlyMap<string, PluginDataParam[]>;
  /** The install's settings by key, which a part's text names. */
  settings: Record<string, unknown>;
};

/** The kinds of item whose pages draw plug-ins, as the manifest names them. */
export type PluginItemKind = ItemKind;

/** The kind of item plug-ins draw on that a detail lays out, or null for one
 *  they draw nothing on (a file opened from a collection). */
export const pluginKindOf = (kind: DetailLayoutReadKind): PluginItemKind | null =>
  Object.hasOwn(ItemKind, kind) ? (kind as PluginItemKind) : null;

/** What a block declares on one kind of item, of what the server offers the
 *  reader. */
const declared = <T extends { on: string[] }>(
  definition: object,
  block: string,
  id: keyof T,
  offered: string[],
  kind: PluginItemKind
) => {
  const entries = (definition as Record<string, unknown>)[block];
  return new Map(
    (Array.isArray(entries) ? (entries as T[]) : [])
      .filter((entry) => Array.isArray(entry?.on) && entry.on.includes(kind))
      .filter((entry) => offered.includes(String(entry[id])))
      .map((entry) => [String(entry[id]), entry])
  );
};

/** Each endpoint's parameters, by id. */
const endpointParams = (definition: object): ReadonlyMap<string, PluginDataParam[]> => {
  const entries = (definition as Record<string, unknown>).endpoints;
  return new Map(
    (Array.isArray(entries) ? (entries as { id: string; params?: PluginDataParam[] }[]) : [])
      .filter((entry) => typeof entry?.id === "string")
      .map((entry) => [entry.id, Array.isArray(entry.params) ? entry.params : []])
  );
};

/** The installs whose values, parts and actions a reader meets on one kind of
 *  item in one initiative. */
export const pluginsOnItems = (
  installs: Pick<
    CommunityPluginRead,
    | "id"
    | "name"
    | "enabled"
    | "definition"
    | "item_initiatives"
    | "item_fields"
    | "item_parts"
    | "item_actions"
    | "setting_values"
  >[],
  initiativeId: number,
  kind: PluginItemKind = "task"
): ReadonlyMap<number, PluginOnItems> =>
  new Map(
    installs
      .filter((install) => install.enabled && install.item_initiatives.includes(initiativeId))
      .map((install) => {
        return [
          install.id,
          {
            id: install.id,
            kind,
            name: install.name,
            fields: declared<PluginFieldDecl>(
              install.definition,
              "fields",
              "key",
              install.item_fields,
              kind
            ),
            parts: declared<PluginPartDecl>(
              install.definition,
              "parts",
              "id",
              install.item_parts,
              kind
            ),
            actions: declared<PluginActionDecl>(
              install.definition,
              "actions",
              "id",
              install.item_actions,
              kind
            ),
            endpoints: endpointParams(install.definition),
            settings: install.setting_values ?? {},
          },
        ];
      })
  );

const NO_PLUGINS: ReadonlyMap<number, PluginOnItems> = new Map();

/** {@link pluginsOnItems} for the community's installs, once they load. A
 *  kind plug-ins draw nothing on (null) has none. */
export const usePluginsOnItems = (
  initiativeId: number | null | undefined,
  enabled = true,
  kind: PluginItemKind | null = "task"
): ReadonlyMap<number, PluginOnItems> => {
  const { data } = useCommunityPlugins({
    enabled: enabled && initiativeId != null && kind !== null,
  });
  return useMemo(
    () =>
      data && initiativeId != null && kind !== null
        ? pluginsOnItems(data.items, initiativeId, kind)
        : NO_PLUGINS,
    [data, initiativeId, kind]
  );
};

/** A plug-in field's id in a view: by install and key, as the server checks it. */
export const pluginFieldId = (install: number, key: string) => `plugin:${install}:${key}`;

/** The type each kind of plug-in field is filtered like: by its words, or by
 *  its number (a scale's figure, an amount, a date's day). A kind not here is
 *  not offered as a filter. */
const FILTERED_AS: Partial<Record<PluginFieldKind, MetadataType>> = {
  text: MetadataType.text,
  badge: MetadataType.text,
  link: MetadataType.text,
  url: MetadataType.text,
  number: MetadataType.number,
  currency: MetadataType.number,
  scale: MetadataType.scale,
  checkbox: MetadataType.checkbox,
  date: MetadataType.date,
  datetime: MetadataType.datetime,
};

/** The plug-in fields a task list can be filtered by, as the reader is drawn
 *  them. A list holds several values, which one filter does not compare. */
export const pluginFilterFields = (
  plugins: ReadonlyMap<number, PluginOnItems>,
  language: string
): PluginFilterField[] =>
  [...plugins.values()].flatMap(({ id, fields }) =>
    [...fields.values()]
      .filter((field) => !field.list && Object.hasOwn(FILTERED_AS, field.kind))
      .map((field) => ({
        id: pluginFieldId(id, field.key),
        name: localized(field.name, language) ?? field.key,
        type: FILTERED_AS[field.kind] as MetadataType,
      }))
  );

/** How many parts of one install a tree may place, as the contract says. */
export const MAX_PLUGIN_PARTS = contract.caps.partsPlacedPerItem;

/** What an item's page draws of the plug-ins until its layout is saved: each
 *  install's fields, then its parts up to {@link MAX_PLUGIN_PARTS}, as it
 *  declares them. A field a drawn part also shows is drawn there only
 *  ({@link FieldsInParts}). */
export const shippedPluginParts = (plugins: ReadonlyMap<number, PluginOnItems>): LayoutNode[] =>
  [...plugins.values()].flatMap(({ id, fields, parts }) => [
    ...[...fields.keys()].map((key) => ({
      type: "field",
      props: { field: pluginFieldId(id, key) },
    })),
    ...[...parts.keys()]
      .slice(0, MAX_PLUGIN_PARTS)
      .map((part) => ({ type: "plugin", props: { plugin: id, part } })),
  ]);

/** Every node of a tree, at any depth. */
const nodesOf = (node: LayoutNode): LayoutNode[] => [
  node,
  ...(node.children ?? []).flatMap(nodesOf),
];

/**
 * The plug-in fields an item's page already shows inside a part it draws, by
 * field id: a part the page places, the reader is offered, and whose tree
 * shows the field. Drawn there, the field is not drawn again on its own. A
 * part that does not draw (taken off, or waiting on a connection) hides
 * nothing, so its fields show on their own.
 */
export const fieldsInParts = (
  root: LayoutNode,
  plugins: ReadonlyMap<number, PluginOnItems>
): Set<string> =>
  new Set(
    nodesOf(root)
      .filter((node) => node.type === "plugin")
      .flatMap((node) => {
        const plugin = plugins.get(Number(node.props?.plugin));
        const part = plugin?.parts.get(String(node.props?.part));
        if (!plugin || !part) return [];
        return nodesOf(part.tree)
          .filter((shown) => shown.type === "field" || shown.type === "value")
          .map((shown) => String(shown.props?.field))
          .filter((key) => plugin.fields.has(key))
          .map((key) => pluginFieldId(plugin.id, key));
      })
  );

/** What the page being drawn shows inside its parts ({@link fieldsInParts}). */
export const FieldsInParts = createContext<ReadonlySet<string>>(new Set());

/** What an install keeps under `key` on an item, among its values: the value,
 *  with the options and currency its definition reads with. */
const pluginSummary = (values: PropertySummary[] | undefined, install: number, key: string) =>
  values?.find((value) => value.install_id === install && value.key === key);

/** The value an install keeps under `key` on an item. */
const pluginValue = (values: PropertySummary[] | undefined, install: number, key: string) =>
  pluginSummary(values, install, key)?.value ?? null;

/** Every field the installs show on a task, after the built-ins and properties. */
export const pluginFields = (
  plugins: ReadonlyMap<number, PluginOnItems>,
  language: string
): FieldDef[] =>
  [...plugins.values()].flatMap((plugin) =>
    [...plugin.fields.values()].map(
      (field): FieldDef => ({
        id: pluginFieldId(plugin.id, field.key),
        kind: "plugin",
        source: "plugin",
        label: localized(field.name, language) ?? field.key,
        hideable: true,
        // What a plug-in fills is the plug-in's.
        requireable: false,
        plugin: { install: plugin.id, field, on: plugin },
        value: (task) => {
          const value = pluginValue(task.properties, plugin.id, field.key);
          return draws(field, value) ? value : null;
        },
      })
    )
  );

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isWebLink = (url: unknown): url is string =>
  typeof url === "string" && (url.startsWith("https://") || url.startsWith("http://"));

/** The kinds whose value is one scalar, which a value kept beside a state,
 *  and a list's element, hold in `value`. */
const SCALAR_KINDS = new Set<PluginFieldKind>([
  "text",
  "number",
  "scale",
  "date",
  "datetime",
  "checkbox",
  "url",
  "currency",
  "select",
  "multi_select",
  "user_reference",
]);

/** The kinds that are property types, drawn as a property's value is, with
 *  the options and currency the value is read with. */
const PROPERTY_KINDS = new Set<PluginFieldKind>([
  "url",
  "currency",
  "select",
  "multi_select",
  "user_reference",
]);

/** A value as its kind reads it. */
const scalarOf = (kind: PluginFieldKind, value: unknown): unknown =>
  SCALAR_KINDS.has(kind) && isObject(value) && "value" in value ? value.value : value;

/** The keys of each state facet a value is in, by facet, when it names any. */
const stateOf = (value: unknown): Record<string, string> | undefined => {
  if (!isObject(value) || !isObject(value.state)) return undefined;
  const states = Object.entries(value.state).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string"
  );
  return states.length ? Object.fromEntries(states) : undefined;
};

/** One element of a list field's value. */
type Element = { ref: string } & Record<string, unknown>;

const isElement = (value: unknown): value is Element =>
  isObject(value) && typeof value.ref === "string" && value.ref !== "";

/** Whether a value is one its kind draws. A value of another shape draws
 *  nothing, as an empty one does. */
const shows = (kind: PluginFieldKind, raw: unknown): boolean => {
  const value = scalarOf(kind, raw);
  switch (kind) {
    case "text":
    case "date":
    case "datetime":
    case "url":
    case "select":
      return typeof value === "string" && value !== "";
    case "number":
    case "scale":
    case "currency":
      return typeof value === "number" && Number.isFinite(value);
    case "multi_select":
      return Array.isArray(value) && value.some((each) => typeof each === "string");
    case "user_reference":
      return (typeof value === "number" && Number.isFinite(value)) || isObject(value);
    case "checkbox":
      return typeof value === "boolean";
    case "link":
      return isObject(value) && isWebLink(value.url);
    case "badge":
      return isObject(value) && typeof value.text === "string" && value.text !== "";
  }
};

/** The elements of a list field's value its kind draws, in the list's order. */
const elementsOf = (field: PluginFieldDecl, value: unknown): Element[] =>
  field.list && Array.isArray(value)
    ? value.filter(isElement).filter((element) => shows(field.kind, element))
    : [];

/** Whether a field's value draws anything: one of its kind, or a list with
 *  an element of it. */
const draws = (field: PluginFieldDecl, value: unknown): boolean =>
  field.list ? elementsOf(field, value).length > 0 : shows(field.kind, value);

const TEXT_TONE: Record<Tone, string> = {
  accent: "text-primary",
  positive: "text-success",
  negative: "text-destructive",
  warning: "text-warning",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
};

const BADGE_TONE: Record<Tone, string> = {
  accent: "border-primary/40 text-primary",
  positive: "border-success/40 text-success",
  negative: "border-destructive/40 text-destructive",
  warning: "border-warning/40 text-warning",
  neutral: "",
  muted: "text-muted-foreground",
};

const toneOf = (tone: unknown, fallback: Tone | undefined): Tone =>
  typeof tone === "string" && Object.hasOwn(TEXT_TONE, tone)
    ? (tone as Tone)
    : (fallback ?? "neutral");

/** One value of a field's kind, with the badge of each state it is in. A
 *  property type's is drawn as a property's, read with what `kept` carries. */
const PluginScalar = ({
  field,
  value: raw,
  kept,
}: {
  field: PluginFieldDecl;
  value: unknown;
  kept?: PropertySummary;
}) => {
  const { t, i18n } = useTranslation("common");
  if (!shows(field.kind, raw)) return null;
  const value = scalarOf(field.kind, raw);
  if (PROPERTY_KINDS.has(field.kind)) {
    return (
      <StatedValue field={field} raw={raw}>
        <PropertyValueCell
          summary={{
            property_id: kept?.property_id ?? 0,
            name: kept?.name ?? field.key,
            type: field.kind as MetadataType,
            project_id: null,
            collection_id: null,
            install_id: kept?.install_id ?? null,
            key: field.key,
            options: kept?.options ?? null,
            currency: kept?.currency ?? null,
            value,
          }}
        />
      </StatedValue>
    );
  }
  const drawn = (() => {
    switch (field.kind) {
      case "text":
        return <span className="wrap-break-word">{value as string}</span>;
      case "number":
        return <span>{numberFormat(i18n.language).format(value as number)}</span>;
      case "date":
        return <span>{formatDate(value)}</span>;
      case "datetime":
        return <span>{formatDateTime(value)}</span>;
      case "checkbox":
        return value ? (
          <Check className="h-4 w-4" aria-label={t("yes")} />
        ) : (
          <Minus className="h-4 w-4 text-muted-foreground" aria-label={t("no")} />
        );
      case "link": {
        const link = value as { url: string; text?: unknown };
        return (
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-w-0 items-center gap-1 text-primary underline-offset-4 hover:underline"
          >
            <span className="truncate">
              {typeof link.text === "string" && link.text ? link.text : link.url}
            </span>
            <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
          </a>
        );
      }
      case "badge": {
        const badge = value as { text: string; tone?: unknown };
        return (
          <Badge variant="outline" className={BADGE_TONE[toneOf(badge.tone, field.tone)]}>
            {badge.text}
          </Badge>
        );
      }
      case "scale":
        return <ScaleValue value={Math.min(100, Math.max(0, value as number))} display="bar" />;
    }
  })();
  return (
    <StatedValue field={field} raw={raw}>
      {drawn}
    </StatedValue>
  );
};

/** A value drawn beside the badge of each state it is in, as its field names
 *  them. */
const StatedValue = ({
  field,
  raw,
  children,
}: {
  field: PluginFieldDecl;
  raw: unknown;
  children: ReactNode;
}) => {
  const { i18n } = useTranslation();
  const states = Object.entries(stateOf(raw) ?? {}).flatMap(([facet, key]) => {
    const state = field.states?.[facet]?.values[key];
    return state ? [{ facet, key, ...state }] : [];
  });
  if (!states.length) return children;
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-1">
      {children}
      {states.map((state) => (
        <Badge
          key={state.facet}
          variant="outline"
          className={BADGE_TONE[toneOf(state.tone, "neutral")]}
        >
          {localized(state.label, i18n.language) ?? state.key}
        </Badge>
      ))}
    </span>
  );
};

/** The actions a list field offers on each of its elements, and how to run
 *  one from an element. */
type ElementActions = {
  offered: PluginActionDecl[];
  start: (action: PluginActionDecl, ref: string) => void;
  pending: boolean;
};

const elementActions = (
  plugin: PluginOnItems,
  field: PluginFieldDecl,
  start: (plugin: PluginOnItems, action: PluginActionDecl, element?: string) => void,
  pending: boolean
): ElementActions | undefined => {
  const offered = (field.actions ?? []).flatMap((id) => {
    const action = plugin.actions.get(id);
    return action ? [action] : [];
  });
  return offered.length
    ? { offered, start: (action, ref) => start(plugin, action, ref), pending }
    : undefined;
};

/** A plug-in value, drawn as its kind is: one value, or a list's elements,
 *  each with the actions the list offers on it where there is a way to run
 *  them. */
const PluginValue = ({
  field,
  kept,
  elements,
}: {
  field: PluginFieldDecl;
  /** What the install keeps under the field's key on the item. */
  kept: PropertySummary | undefined;
  elements?: ElementActions;
}) => {
  const { i18n } = useTranslation();
  const value = kept?.value ?? null;
  if (!field.list) return <PluginScalar field={field} value={value} kept={kept} />;
  const drawn = elementsOf(field, value);
  if (!drawn.length) return null;
  return (
    <ul className="space-y-1">
      {drawn.map((element) => (
        <li key={element.ref} className="flex min-w-0 flex-wrap items-center gap-2">
          <PluginScalar field={field} value={element} kept={kept} />
          {elements?.offered.map((action) => (
            <Button
              key={action.id}
              type="button"
              size="sm"
              variant="ghost"
              disabled={elements.pending}
              onClick={() => elements.start(action, element.ref)}
            >
              {localized(action.name, i18n.language) ?? action.id}
            </Button>
          ))}
        </li>
      ))}
    </ul>
  );
};

/** A plug-in field as a view draws it: its value in a cell, and its name
 *  beside its value on a card. */
export const PluginField = ({ value, item, field, variant }: FieldRendererProps) => {
  if (!field.plugin || value === null) return null;
  const { install, field: declared } = field.plugin;
  const drawn = (
    <PluginValue field={declared} kept={pluginSummary(item.properties, install, declared.key)} />
  );
  if (variant === "cell") return drawn;
  return (
    <span className="inline-flex min-w-0 items-center gap-1 text-xs">
      <span className="text-muted-foreground">{field.label}</span>
      {drawn}
    </span>
  );
};

/** A plug-in field on a detail: its name above its value, which the
 *  plug-in alone changes, and the actions a list offers on each element. */
export const PluginFieldOnDetail = ({ field, item }: { field: FieldDef; item: PluginItem }) => {
  const inParts = useContext(FieldsInParts);
  const runner = useActionRunner(field.plugin?.on.kind ?? "task", item.id);
  if (!field.plugin || inParts.has(field.id)) return null;
  const { install, field: declared, on } = field.plugin;
  const kept = pluginSummary(item.properties, install, declared.key);
  if (!draws(declared, kept?.value ?? null)) return null;
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-xs">{field.label}</p>
      <div className="text-sm">
        <PluginValue
          field={declared}
          kept={kept}
          elements={elementActions(on, declared, runner.start, runner.pending)}
        />
      </div>
      {runner.dialog}
    </div>
  );
};

// -- Actions --------------------------------------------------------------------

/** An action about to run, once the reader has answered what it asks. */
type Asking = { plugin: PluginOnItems; action: PluginActionDecl; element?: string };

/** What an action asks the reader for: the parameters it names, as its
 *  endpoint declares them. */
const askedParams = ({ plugin, action }: Asking): PluginDataParam[] =>
  (plugin.endpoints.get(action.endpoint ?? "") ?? []).filter((param) =>
    action.params?.includes(param.key)
  );

/** An action's question: a form for the parameters it asks for, with what it
 *  says to confirm, if anything, above them. */
const PluginActionDialog = ({
  asking,
  onClose,
  onRun,
}: {
  asking: Asking;
  onClose: () => void;
  onRun: (params: Record<string, unknown>) => void;
}) => {
  const { t, i18n } = useTranslation("common");
  const formId = useId();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const params = askedParams(asking);
  const ready = params.every((param) => !param.required || values[param.key] !== undefined);
  const name = localized(asking.action.name, i18n.language) ?? asking.action.id;
  const confirm = localized(asking.action.confirm, i18n.language);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
          {confirm ? <DialogDescription>{confirm}</DialogDescription> : null}
        </DialogHeader>
        <form
          id={formId}
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (ready) onRun(values);
          }}
        >
          {params.map((param) => (
            <PluginParamControl
              key={param.key}
              param={param}
              pluginId={asking.plugin.id}
              endpointId={asking.action.endpoint}
              values={values}
              open
              onChange={(key, value) =>
                setValues((current) => withParamAnswer(params, current, key, value))
              }
            />
          ))}
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={!ready}>
            {name}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/** Runs a plug-in's actions on an item, asking first when the action says
 *  to, or asks for something. */
const useActionRunner = (kind: PluginItemKind, itemId: number) => {
  const { t, i18n } = useTranslation("common");
  const run = useRunPluginAction();
  const [asking, setAsking] = useState<Asking | null>(null);
  const start = (plugin: PluginOnItems, action: PluginActionDecl, element?: string) => {
    if (action.confirm || action.params?.length) setAsking({ plugin, action, element });
    else run.mutate({ pluginId: plugin.id, actionId: action.id, kind, itemId, element });
  };
  const close = () => setAsking(null);
  const asks = asking !== null && (asking.action.params?.length ?? 0) > 0;
  const dialog = (
    <>
      {asking && asks && (
        <PluginActionDialog
          key={`${asking.plugin.id}:${asking.action.id}`}
          asking={asking}
          onClose={close}
          onRun={(params) => {
            run.mutate({
              pluginId: asking.plugin.id,
              actionId: asking.action.id,
              kind,
              itemId,
              params,
              element: asking.element,
            });
            close();
          }}
        />
      )}
      <ConfirmDialog
        open={asking !== null && !asks}
        onOpenChange={(open) => {
          if (!open) close();
        }}
        title={asking ? (localized(asking.action.confirm, i18n.language) ?? "") : ""}
        confirmLabel={
          asking ? (localized(asking.action.name, i18n.language) ?? asking.action.id) : ""
        }
        cancelLabel={t("cancel")}
        onConfirm={() => {
          if (asking) {
            run.mutate({
              pluginId: asking.plugin.id,
              actionId: asking.action.id,
              kind,
              itemId,
              element: asking.element,
            });
          }
          close();
        }}
      />
    </>
  );
  return { start, pending: run.isPending, dialog };
};

/** An item's menu entries for the actions plug-ins offer there, and the
 *  question one asks before it runs, which stays when the menu closes. */
export const usePluginMenuActions = (
  kind: PluginItemKind,
  itemId: number,
  initiativeId: number | null | undefined
) => {
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(initiativeId, true, kind);
  const runner = useActionRunner(kind, itemId);
  const items = [...plugins.values()].flatMap((plugin) =>
    [...plugin.actions.values()]
      .filter((action) => action.menu)
      .map((action) => (
        <DropdownMenuItem
          key={`${plugin.id}:${action.id}`}
          disabled={runner.pending}
          onSelect={() => runner.start(plugin, action)}
        >
          {localized(action.name, i18n.language) ?? action.id}
        </DropdownMenuItem>
      ))
  );
  return { items, dialog: runner.dialog };
};

// -- Parts ----------------------------------------------------------------------

const GAP = { none: "gap-0", small: "gap-1", medium: "gap-2", large: "gap-4" };
const BUTTON_VARIANT = { primary: "default", secondary: "outline", ghost: "ghost" } as const;

/** What a part's text may name: the item's id, and one of the install's
 *  settings. */
const PLACEHOLDER = /\{item\.id\}|\{settings\.([^}]+)\}/g;

/** A part's text with its placeholders filled in. A setting with no value
 *  fills in as nothing. */
export const filledText = (
  text: string,
  item: PluginItem,
  settings: Record<string, unknown>
): string =>
  text.replace(PLACEHOLDER, (_match, key?: string) => {
    if (key === undefined) return String(item.id);
    const value = settings[key];
    return value === undefined || value === null ? "" : String(value);
  });

type Drawing = {
  plugin: PluginOnItems;
  item: PluginItem;
  language: string;
  start: (plugin: PluginOnItems, action: PluginActionDecl, element?: string) => void;
  pending: boolean;
};

const drawChildren = (node: LayoutNode, drawing: Drawing): ReactNode =>
  node.children?.map((child, index) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: a part's tree is fixed by its manifest
    <Fragment key={index}>{drawPart(child, drawing)}</Fragment>
  ));

const drawPart = (node: LayoutNode, drawing: Drawing): ReactNode => {
  const props = node.props ?? {};
  const { plugin, item, language } = drawing;
  switch (node.type) {
    case "section":
      return (
        <Section
          title={localized(props.title as LocalizedText | undefined, language)}
          collapsed={props.collapsed === true}
          spacing="space-y-2"
        >
          {drawChildren(node, drawing)}
        </Section>
      );
    case "stack":
      return (
        <div
          className={cn(
            "flex min-w-0",
            props.direction === "row" ? "flex-row items-center" : "flex-col",
            props.wrap === true && "flex-wrap",
            GAP[(props.gap as keyof typeof GAP) ?? "medium"] ?? GAP.medium
          )}
        >
          {drawChildren(node, drawing)}
        </div>
      );
    case "field":
    case "value": {
      const field = plugin.fields.get(String(props.field));
      if (!field) return null;
      const kept = pluginSummary(item.properties, plugin.id, field.key);
      if (!draws(field, kept?.value ?? null)) return null;
      const drawn = (
        <PluginValue
          field={field}
          kept={kept}
          elements={elementActions(plugin, field, drawing.start, drawing.pending)}
        />
      );
      if (node.type === "value") return drawn;
      return (
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">
            {localized(field.name, language) ?? field.key}
          </p>
          <div className="text-sm">{drawn}</div>
        </div>
      );
    }
    case "text": {
      const text = localized(props.text as LocalizedText | undefined, language);
      return text ? (
        <p className={cn("wrap-break-word text-sm", TEXT_TONE[toneOf(props.tone, "neutral")])}>
          {filledText(text, item, plugin.settings)}
        </p>
      ) : null;
    }
    case "button": {
      const action = plugin.actions.get(String(props.action));
      if (!action) return null;
      return (
        <Button
          type="button"
          size="sm"
          variant={
            BUTTON_VARIANT[(props.variant as keyof typeof BUTTON_VARIANT) ?? "secondary"] ??
            "outline"
          }
          disabled={drawing.pending}
          onClick={() => drawing.start(plugin, action)}
        >
          {localized(action.name, language) ?? action.id}
        </Button>
      );
    }
    default:
      return null;
  }
};

/** One of a plug-in's parts on an item, drawn from its manifest's tree. A part
 *  the install no longer declares, or one placed where its plug-in does not
 *  reach the reader, draws nothing. */
export const PluginPartView = ({
  plugins,
  pluginId,
  partId,
  item,
}: {
  plugins: ReadonlyMap<number, PluginOnItems> | undefined;
  pluginId: number;
  partId: string;
  item: PluginItem;
}) => {
  const { i18n } = useTranslation();
  const plugin = plugins?.get(pluginId);
  const runner = useActionRunner(plugin?.kind ?? "task", item.id);
  const part = plugin?.parts.get(partId);
  if (!plugin || !part) return null;
  return (
    <>
      {drawPart(part.tree, {
        plugin,
        item,
        language: i18n.language,
        start: runner.start,
        pending: runner.pending,
      })}
      {runner.dialog}
    </>
  );
};
