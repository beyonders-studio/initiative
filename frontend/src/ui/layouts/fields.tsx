import type { LucideIcon } from "lucide-react";
import { type ComponentType, memo, type ReactNode } from "react";

import {
  MetadataType,
  type PropertyDefinitionRead,
  type PropertySummary,
  type TaskListRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";
import { DateCell } from "@/ui/date-cell";
import { host } from "@/ui/host";
import { formatDateTime } from "@/ui/lib/formatDate";
import { cn } from "@/ui/lib/utils";
import { PropertyValueCell } from "@/ui/properties/PropertyValueCell";
import { namePropertyColumns } from "@/ui/properties/propertyColumns";
import type { FieldDisplay } from "@/ui/properties/propertyHelpers";
import { iconForPropertyType } from "@/ui/properties/propertyTypeIcons";

import type { PropertyEnv } from "./fieldEditors";

/** What a view draws, typed as a listed task: another kind's fields read its
 *  own item off it. */
export type LayoutItem = TaskListRead;

/** Where a field is drawn. On a detail it is its editor, which the kind of
 *  item's detail parts draw. */
export type LayoutVariant = "card" | "cell" | "detail";

/** The kinds of field drawn here. A kind of item draws its own fields
 *  ({@link FieldDef}'s `render`). */
export type FieldKind = "title" | "excerpt" | "date" | "count" | "property";

/** A property's field, by its definition id: what a view stores, so renaming
 *  the property keeps every view that shows it. */
export const PROPERTY_FIELD_PREFIX = "property:";
export const propertyFieldId = (definitionId: number) => `${PROPERTY_FIELD_PREFIX}${definitionId}`;

/** Fields of one owner, under the heading a list of them shows. */
export type FieldGroup = {
  key: string;
  /** An i18n key, or a plug-in's own name where `plugin` is set. */
  heading: string;
  /** The install whose fields these are. */
  plugin?: number;
  fields: FieldDef[];
};

/** The owners a field may have, in the order they are listed, by heading. */
const OWNER_GROUPS = [
  ["builtIn", "layouts:builtIn"],
  ["projectMetadata", "layouts:projectProperties"],
  ["collectionMetadata", "layouts:collectionProperties"],
  ["properties", "layouts:initiativeMetadata"],
] as const;

const ownerOf = (field: FieldDef): (typeof OWNER_GROUPS)[number][0] =>
  field.source === "builtin"
    ? "builtIn"
    : field.property?.project_id
      ? "projectMetadata"
      : field.property?.collection_id
        ? "collectionMetadata"
        : "properties";

/**
 * `fields` grouped by who they belong to: the tool's own, a project's or a
 * collection's metadata, the initiative's properties, then each plug-in's
 * under its name. A group with nothing in it is left out.
 */
export const groupFields = (fields: readonly FieldDef[]): FieldGroup[] => {
  const installs = new Map<number, FieldGroup>();
  for (const field of fields) {
    if (!field.plugin) continue;
    const { install, name } = field.plugin;
    const group = installs.get(install) ?? {
      key: `plugin:${install}`,
      heading: name,
      plugin: install,
      fields: [],
    };
    group.fields.push(field);
    installs.set(install, group);
  }
  return [
    ...OWNER_GROUPS.map(([owner, heading]) => ({
      key: owner,
      heading,
      fields: fields.filter((field) => !field.plugin && ownerOf(field) === owner),
    })),
    ...installs.values(),
  ].filter((group) => group.fields.length > 0);
};

/** Anything a view can show about an item. */
export type FieldDef = {
  id: string;
  /** The kind of value it holds, drawn as {@link FIELD_RENDERERS} draws that
   *  kind. Left out where `render` draws it, or nothing does. */
  kind?: FieldKind;
  /** How the kind of item draws a field of its own, in place of its kind's. */
  render?: ComponentType<FieldRendererProps>;
  source: "builtin" | "property" | "plugin";
  /** Built-in: an i18n key, in the words its kind reads with (`LayoutEnv`'s
   *  `t`). Property or plug-in field: its own name, untranslated. */
  label: string;
  /** What the field holds for an item. Nothing (null, "", []) draws nothing on
   *  a card; a cell says so. */
  value: (item: LayoutItem) => unknown;
  /** A title cannot be hidden: a card with no title is not a card. */
  hideable: boolean;
  /** Whether an item's page can require it: a value a person fills in that
   *  can be left empty. A title is always required; what is never empty, what
   *  a plug-in fills and what nobody fills cannot be. */
  requireable: boolean;
  /** A plug-in field's install, and what the community calls it: a list of
   *  fields groups the install's under that name. */
  plugin?: { install: number; name: string };
  /** A property field's definition. */
  property?: PropertyDefinitionRead;
  /** How a scale or a counter is drawn where the list showing it says. */
  display?: FieldDisplay;
  /** A property drawn on a card as its value alone, not named: a card under
   *  a picture, which reads as a caption or a price rather than a row of
   *  labelled chips. */
  plain?: boolean;
  /** The sentence the value sits in, as an i18n key ("Due: {{date}}"). */
  phrase?: string;
  icon?: LucideIcon;
  tone?: "warning";
  /** How a cell marks a date that has passed: as begun, or as overdue until
   *  the item is `done`. */
  past?: "primary" | "destructive";
  /** Whether the item is done, past which none of its dates is overdue. */
  done?: (item: LayoutItem) => boolean;
};

/** What renderers share across a view. It changes with the language, the
 *  community and the item links, not with which fields are shown, so a renderer
 *  whose value is unchanged skips redrawing when the Fields menu changes. */
export type LayoutEnv = {
  /** Reads the kind's words: its fields' labels and phrases. What the kit
   *  says it reads by prefix (`layouts:`), so it loads `layouts` beside them. */
  t: (key: string, options?: Record<string, unknown>) => string;
  /** A community-relative path, made absolute in the item's community. */
  communityPath: (path: string, item: LayoutItem) => string;
  /** The page an item's title opens. */
  itemHref: (item: LayoutItem) => string;
  /** What can be done with an item from where it is drawn, beside its title
   *  on a card: a board its reader may change. */
  itemActions?: ComponentType<{ item: LayoutItem }>;
  /** Steps a counter on an item where the list's reader may change it there,
   *  answering with the item's values as the server then holds them. Left
   *  out, or answering null for an item they may not change, a counter is
   *  drawn without its buttons. */
  stepCounter?: (
    item: LayoutItem,
    definition: PropertyDefinitionRead
  ) => ((up: boolean) => Promise<PropertySummary[]>) | null;

  /** What its property editors read and change through: a detail's. Left
   *  out, its properties are read, not changed. */
  properties?: PropertyEnv;
};

export type FieldRendererProps = {
  value: unknown;
  item: LayoutItem;
  field: FieldDef;
  variant: LayoutVariant;
  env: LayoutEnv;
  /** Drawn on one line ({@link LayoutContext}'s `oneLine`). */
  oneLine?: boolean;
};

/** Whether a value has nothing to show. A count of none is null by then. */
export const isEmptyValue = (value: unknown): boolean =>
  value == null || value === "" || (Array.isArray(value) && value.length === 0);

/** One field per property the initiative defines, two that share a name told
 *  apart in their labels; `read` reads one's value off an item. */
export const propertyFields = (
  definitions: PropertyDefinitionRead[],
  read: (item: LayoutItem, definition: PropertyDefinitionRead) => unknown
): FieldDef[] =>
  namePropertyColumns(definitions).map(({ definition, label }) => ({
    id: propertyFieldId(definition.id),
    kind: "property",
    source: "property",
    label,
    hideable: true,
    // A checkbox is always on or off, so never empty.
    requireable: definition.type !== MetadataType.checkbox,
    icon: iconForPropertyType(definition.type),
    value: (item) => read(item, definition),
    property: definition,
  }));

/**
 * An item's title, as a link to its page. Only the title opens the item: the
 * rest of the card is the card, and a real link means middle-click and "open
 * in new tab" work. A kind of item may mark it (`mark`), inside the link.
 */
export const TitleField = ({
  value,
  item,
  variant,
  env,
  mark,
}: FieldRendererProps & { mark?: ReactNode }) => {
  const Actions = variant === "card" ? env.itemActions : undefined;
  const link = (
    <host.Link
      to={env.itemHref(item)}
      draggable={false}
      className="wrap-break-word w-full min-w-0 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-1 focus-visible:ring-ring"
    >
      {value as string}
      {mark}
    </host.Link>
  );
  if (!Actions) return link;
  return (
    <div className="flex w-full min-w-0 items-start gap-1">
      {link}
      <Actions item={item} />
    </div>
  );
};

/** Two lines of words, not a picture that fills the card. A kind of item may
 *  draw the words its own way (`children`). */
export const ExcerptField = ({
  value,
  children,
}: FieldRendererProps & { children?: ReactNode }) => (
  <p className="wrap-break-word line-clamp-2 w-full min-w-0 text-muted-foreground text-sm">
    {children ?? (value as string)}
  </p>
);

// `formatDateTime`, as every timestamp in the app: it honours the reader's
// 12/24-hour choice. A cell says how far off the date is instead.
const DateField = ({ value, item, field, variant, env }: FieldRendererProps) => {
  if (variant === "cell") {
    return (
      <DateCell
        date={value as string | null}
        isPastVariant={field.past}
        isDone={field.done?.(item)}
      />
    );
  }
  const date = formatDateTime(value as string);
  if (!date) return null;
  return <p>{field.phrase ? env.t(field.phrase, { date }) : date}</p>;
};

const CountField = ({ value, field, variant, env }: FieldRendererProps) => {
  const count = value as number | null;
  const Icon = field.icon;
  if (variant === "cell") {
    return count ? (
      <span className="inline-flex items-center gap-1 text-sm">
        {Icon ? <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" /> : null}
        {count}
      </span>
    ) : (
      <span className="text-muted-foreground text-sm">0</span>
    );
  }
  return (
    <Badge
      variant="outline"
      className={cn(
        "inline-flex items-center gap-1 text-xs",
        field.tone === "warning" && "border-warning/40 text-warning"
      )}
      title={field.phrase ? env.t(field.phrase, { count }) : undefined}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" aria-hidden="true" /> : null}
      {count}
    </Badge>
  );
};

const PropertyField = ({ value, item, field, variant, env, oneLine }: FieldRendererProps) => {
  const summary = (value as PropertySummary | null) ?? undefined;
  const step =
    summary && field.property?.type === MetadataType.counter
      ? env.stepCounter?.(item, field.property)
      : null;
  return (
    <PropertyValueCell
      summary={summary}
      variant={variant === "cell" || field.plain ? "cell" : "chip"}
      display={field.display}
      oneLine={oneLine}
      onStep={step ?? undefined}
    />
  );
};

/** `fields`, each scale or counter drawn as a list's `displays` say. */
export const withDisplays = <F extends Pick<FieldDef, "display">>(
  fields: ReadonlyMap<string, F>,
  displays: Readonly<Record<string, FieldDisplay>> | null | undefined
): ReadonlyMap<string, F> =>
  displays && Object.keys(displays).length > 0
    ? new Map(
        [...fields].map(([id, field]) => [
          id,
          id in displays ? { ...field, display: displays[id] } : field,
        ])
      )
    : fields;

/** One renderer per kind of field, each skipping a redraw its props don't call
 *  for. */
const FIELD_RENDERERS: Record<FieldKind, ComponentType<FieldRendererProps>> = {
  title: memo(TitleField),
  excerpt: memo(ExcerptField),
  date: memo(DateField),
  count: memo(CountField),
  property: memo(PropertyField),
};

const NOTHING = () => null;

/** What draws a field: its own renderer, else its kind's; nothing for neither. */
export const fieldRenderer = (field: FieldDef): ComponentType<FieldRendererProps> =>
  field.render ?? (field.kind ? FIELD_RENDERERS[field.kind] : NOTHING);
