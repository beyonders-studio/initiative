/**
 * Field editors any detail shares (a task's, an event's): the title, the
 * colour and the custom properties, each saved on its own through the saves
 * of the item's kind. What they read and look up comes in from the page
 * around them, and what they change goes out through it.
 */

import { X } from "lucide-react";
import {
  type ReactNode,
  type RefObject,
  type TextareaHTMLAttributes,
  useContext,
  useLayoutEffect,
  useRef,
} from "react";
import { useTranslation } from "react-i18next";

import {
  MetadataType,
  type PropertyDefinitionRead,
  type PropertySummary,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { host } from "@/ui/host";
import { cn } from "@/ui/lib/utils";
import type { SearchMembers } from "@/ui/member-picker";
import { AddPropertyButton } from "@/ui/properties/AddPropertyButton";
import type { FileFieldFiles } from "@/ui/properties/FileFieldInput";
import type { CreateProperty } from "@/ui/properties/NewPropertyForm";
import { PropertyInput, type PropertyInputProps } from "@/ui/properties/PropertyInput";
import { PropertyValueCell } from "@/ui/properties/PropertyValueCell";
import {
  isEmptyPropertyValue,
  type MetadataOwner,
  normalizePropertyValue,
  ownProperties,
  propertyStubFromDefinition,
  steppedCount,
  userReferenceValue,
} from "@/ui/properties/propertyHelpers";
import { iconForPropertyType } from "@/ui/properties/propertyTypeIcons";
import { Textarea } from "@/ui/textarea";

import {
  FieldFrame,
  ItemDraftContext,
  type ItemEdit,
  type ItemFieldSave,
  ReadField,
  sameJson,
  useFieldDraft,
} from "./editing";

/**
 * What property editors read and change through, from the page around them
 * (a view's `LayoutEnv` carries it as `properties`): the properties an item
 * may hold, and making a property or an option, finding members and finding
 * and reading files.
 */
export interface PropertyEnv {
  /** What an item may hold: its initiative's properties, and its owner's
   *  metadata where it has an owner. No data until they are read. */
  definitions: {
    data?: PropertyDefinitionRead[];
    isLoading: boolean;
    isError: boolean;
    refetch: () => unknown;
  };
  /** Makes a property named from an item. */
  createProperty: CreateProperty;
  /** Adds an option to a select property. */
  appendOption: PropertyInputProps["appendOption"];
  /** Finds the people a person-valued property may name. */
  searchMembers: SearchMembers;
  /** What a file property picks from, links to and draws. */
  files: FileFieldFiles;
}

/**
 * How the page around an item saves its fields, each on its own. Both are
 * hooks, which a field calls once each time it is drawn.
 */
export interface ItemSaves<I, P> {
  /** One field's save, which its label names in what it says. */
  useSave: (label: string) => ItemFieldSave<I, P>;
  /** The item's properties as the page passed them, with what its saves
   *  answered, and what they have not answered yet, shown over them. */
  useShown: (properties: PropertySummary[]) => PropertySummary[];
}

/** A typed field a typeahead watches: the field, what it holds, and how that
 *  is changed. */
export interface TypeaheadField {
  field: RefObject<HTMLTextAreaElement | null>;
  text: string;
  onChange: (text: string) => void;
  /** Off while the field cannot be changed. */
  enabled: boolean;
}

/** A list a field offers under it as it is typed: told of each change, its
 *  `handlers` spread on the field, and `open` while the list is shown, which
 *  then takes Escape for itself. */
interface Typeahead {
  open: boolean;
  sync: (element: HTMLTextAreaElement, text: string) => void;
  handlers: Pick<TextareaHTMLAttributes<HTMLTextAreaElement>, "onSelect" | "onBlur">;
  popover: ReactNode;
}

const NO_TYPEAHEAD: Typeahead = { open: false, sync: () => {}, handlers: {}, popover: null };
const useNoTypeahead = (): Typeahead => NO_TYPEAHEAD;

const NO_DEFINITIONS: PropertyDefinitionRead[] = [];

/** Without `field-sizing`, a textarea stays as many rows high as it was
 *  given, so it is grown to what it holds, again whenever its width changes. */
const useFittedHeight = (text: string) => {
  const box = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const field = box.current;
    if (!field || CSS.supports("field-sizing", "content")) return;
    let width = -1;
    const grow = () => {
      if (field.clientWidth === width) return;
      width = field.clientWidth;
      field.style.height = "auto";
      field.style.height = `${field.scrollHeight + field.offsetHeight - field.clientHeight}px`;
    };
    grow();
    const observer = new ResizeObserver(grow);
    observer.observe(field);
    return () => observer.disconnect();
  }, [text]);
  return box;
};

/** How a title's text is set, which its marks are set the same way to line up
 *  with it. */
const TITLE_TEXT = "field-sizing-content py-1 font-semibold text-2xl tracking-tight sm:text-3xl";

/**
 * The title's text again, unseen, under the field, with its marked stretches
 * coloured in: the field is clear, so they show through behind the words.
 */
const TitleMarks = ({
  text,
  marks,
}: {
  text: string;
  marks: readonly { start: number; end: number; className: string }[];
}) => {
  const pieces: ReactNode[] = [];
  let from = 0;
  for (const mark of [...marks].sort((a, b) => a.start - b.start)) {
    if (mark.start < from || mark.end > text.length) continue;
    pieces.push(text.slice(from, mark.start));
    pieces.push(
      <mark key={mark.start} className={cn("rounded-sm text-transparent", mark.className)}>
        {text.slice(mark.start, mark.end)}
      </mark>
    );
    from = mark.end;
  }
  pieces.push(text.slice(from));
  return (
    <div
      aria-hidden="true"
      className={cn(
        TITLE_TEXT,
        // The field's own box: its border and padding, wrapped as it wraps.
        "pointer-events-none absolute inset-0 w-full whitespace-pre-wrap break-words rounded-md border border-transparent px-3 text-transparent"
      )}
    >
      {pieces}
    </div>
  );
};

/** An item's title, which is its detail's heading, saved as `field`. It cannot
 *  be emptied: leaving it blank puts the saved one back. A reader who cannot
 *  change it sees the heading alone. */
export const TitleField = <I, P>({
  id,
  label,
  value,
  save,
  readOnly,
  placeholder,
  field = "title",
  optional = false,
  beside,
  marks,
  below,
  trailing,
  useTypeahead = useNoTypeahead,
}: {
  id: string;
  label: string;
  value: string;
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
  field?: string;
  /** It may be emptied, and then reads as `placeholder` (a picture's title,
   *  which falls back to its file's name). */
  optional?: boolean;
  /** Drawn beside the title, read or changed, once the item exists. */
  beside?: ReactNode;
  /** Stretches of the title drawn marked, each with its own class. */
  marks?: readonly { start: number; end: number; className: string }[];
  /** Drawn under the title, inside its frame. */
  below?: ReactNode;
  /** Drawn at the end of the title's first line, beside the field. */
  trailing?: ReactNode;
  /** What the field offers as it is typed: a hook, the same one for as long
   *  as the field is drawn. */
  useTypeahead?: (field: TypeaheadField) => Typeahead;
}) => {
  // One being added may be emptied while it is typed: Add waits for a title.
  const adding = useContext(ItemDraftContext) !== null;
  const besides = (title: ReactNode) =>
    beside && !adding ? (
      <div className="flex min-w-0 grow basis-72 items-start gap-1">
        {title}
        {beside}
      </div>
    ) : (
      title
    );
  const draft = useFieldDraft(value, async (text) => {
    const title = text.trim() ? text : optional ? null : adding ? "" : undefined;
    return title === undefined
      ? false
      : save.save({ patch: { [field]: title } as P, shows: { [field]: title } as Partial<I> });
  });
  const box = useFittedHeight(draft.value);
  const typing = useTypeahead({
    field: box,
    text: draft.value,
    onChange: draft.change,
    enabled: !readOnly,
  });
  if (readOnly) {
    return besides(
      <h1 className="min-w-0 grow basis-72 break-words font-semibold text-2xl tracking-tight sm:text-3xl">
        {value || placeholder}
      </h1>
    );
  }
  return besides(
    <FieldFrame
      label={label}
      htmlFor={id}
      hideLabel
      statusBelow
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      // Too narrow a row for this beside its actions puts them above it.
      className="grow basis-72"
    >
      <h1 className="sr-only">{value}</h1>
      <div className="flex items-start gap-1">
        <div className="relative min-w-0 grow">
          {marks?.length ? <TitleMarks text={draft.value} marks={marks} /> : null}
          {/* One line of text that wraps, so a long title shows whole on a phone. */}
          <Textarea
            ref={box}
            id={id}
            rows={1}
            aria-multiline="false"
            value={draft.value}
            onChange={(event) => {
              const text = event.target.value.replace(/\s*[\r\n]+\s*/g, " ");
              draft.change(text);
              typing.sync(event.target, text);
            }}
            {...typing.handlers}
            // A list open under the field takes Escape for itself.
            data-picking={typing.open || undefined}
            placeholder={placeholder}
            className={cn(
              TITLE_TEXT,
              "relative min-h-0 resize-none shadow-none focus-visible:ring-0"
            )}
          />
          {typing.popover}
        </div>
        {/* Centred on the first line of the title, as tall as it is set. */}
        {trailing ? <div className="mt-1.5 shrink-0 sm:mt-2">{trailing}</div> : null}
      </div>
      {below}
    </FieldFrame>
  );
};

/** What the properties of an item take: how its fields are saved, the item,
 *  who a person-valued property may name, and what they read and change
 *  through. */
type PropertiesProps<I extends { properties: PropertySummary[] }, P> = {
  saves: ItemSaves<I, P>;
  id: number;
  properties: PropertySummary[];
  readOnly: boolean;
  initiativeId: number | null;
  /** Whose people a person-valued property may name: who can open this tool.
   *  Left out (a collection, which has no sharing of its own), the
   *  initiative's members. */
  canOpen?: { tool: Tool; id: number | null | undefined };
  /** The project whose metadata the item holds beside the initiative's
   *  properties: a task's. */
  owner?: MetadataOwner;
  /** When the item last changed, which a signature made before it says. */
  updatedAt?: string | null;
  /** Without it, they are read, not changed. */
  env?: PropertyEnv;
};

/** The item's properties with `property` as it reads after `value`, added
 *  where the item has none of it yet. */
const withValue = (
  properties: PropertySummary[],
  property: PropertySummary,
  value: unknown
): PropertySummary[] =>
  properties.some((p) => p.property_id === property.property_id)
    ? properties.map((p) => (p.property_id === property.property_id ? showing(p, value) : p))
    : [...properties, showing(property, value)];

/** How a value reads on the item until the server says: a person's own
 *  summary while they are still the one named. */
const showing = (property: PropertySummary, value: unknown): PropertySummary => ({
  ...property,
  value: value === normalizePropertyValue(property) ? property.value : value,
});

/** One custom property, saved on its own as its kind says. Only it is sent,
 *  so a change to another property meanwhile still stands. */
const PropertyField = <I extends { properties: PropertySummary[] }, P>({
  saves,
  properties,
  readOnly,
  initiativeId,
  canOpen,
  updatedAt,
  env,
  property,
  placed = false,
}: PropertiesProps<I, P> & {
  env: PropertyEnv;
  property: PropertySummary;
  /** Placed on the layout on its own: it stays when emptied, so its button
   *  clears its value (a checkbox has no empty to click back to) rather than
   *  taking it off the item. */
  placed?: boolean;
}) => {
  const { t } = useTranslation(["properties", "ui"]);
  const save = saves.useSave(property.name);
  const adding = useContext(ItemDraftContext) !== null;
  const saved = normalizePropertyValue(property);
  const person = userReferenceValue(property);
  const edit = (value: unknown): ItemEdit<I, P> => ({
    properties: { values: [{ property_id: property.property_id, value }] },
    shows: { properties: withValue(properties, property, value) } as Partial<I>,
  });
  // A signature cleared can't be put back: writing it again signs it anew,
  // as whoever writes it.
  const restorable = property.type !== MetadataType.signature;
  const draft = useFieldDraft(
    saved,
    (value) =>
      save.save(
        edit(value),
        restorable && isEmptyPropertyValue(value) && !isEmptyPropertyValue(saved)
          ? edit(saved)
          : undefined
      ),
    sameJson
  );
  // A step is taken from what the counter holds when it lands, and shows at
  // once as it reads from here.
  const step = (up: boolean) => {
    draft.restore();
    void save.save({
      properties: { values: [], steps: [{ property_id: property.property_id, up }] },
      shows: {
        properties: withValue(properties, property, steppedCount(property.counter, saved, up)),
      } as Partial<I>,
    });
  };
  // The property stays until it is gone, so a failed removal says so here.
  const remove = () => {
    draft.restore();
    void save.save(
      { properties: { values: [], removed: [property.property_id] }, shows: {} },
      restorable ? { ...edit(saved), shows: { properties } as Partial<I> } : undefined
    );
  };
  return (
    <FieldFrame
      label={property.name}
      save={save}
      changed={draft.changed}
      keys={draft.keys}
      action={
        placed && isEmptyPropertyValue(saved) ? undefined : (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground"
            onClick={placed ? () => draft.edit(null) : remove}
            disabled={readOnly}
            aria-label={placed ? t("ui:clear") : t("remove")}
          >
            <X className="h-4 w-4" />
          </Button>
        )
      }
    >
      <PropertyInput
        definition={property}
        value={draft.value}
        onChange={draft.edit}
        // An item being added has no counter to step yet.
        onStep={adding ? undefined : step}
        disabled={readOnly}
        initiativeId={initiativeId}
        canOpen={canOpen}
        appendOption={env.appendOption}
        searchMembers={env.searchMembers}
        // A person the value names by id alone is looked up.
        selectedUser={
          person && (person.display_name?.trim() || person.username?.trim())
            ? host.member(person)
            : null
        }
        updatedAt={updatedAt}
        files={env.files}
      />
    </FieldFrame>
  );
};

/** Its colour, picked and saved at once. A reader sees the swatch, and
 *  nothing where it has none. */
export const ColorField = <
  I extends { color?: string | null },
  P extends { color?: string | null },
>({
  label,
  value,
  save,
  readOnly,
}: {
  label: string;
  value: string | null | undefined;
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
}) => {
  if (readOnly) {
    return value ? (
      <ReadField label={label}>
        <span className="block h-5 w-5 rounded-full border" style={{ backgroundColor: value }}>
          <span className="sr-only">{value}</span>
        </span>
      </ReadField>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <ColorPickerPopover
        value={value ?? ""}
        onChangeComplete={(color) =>
          void save.save({ patch: { color } as P, shows: { color } as Partial<I> })
        }
        triggerLabel={label}
      />
    </FieldFrame>
  );
};

/**
 * One property placed on the layout on its own: drawn whether or not the item
 * has a value for it yet, and saved on its own. A reader sees it only where it
 * holds a value; a property since deleted draws nothing.
 */
export const PlacedPropertyField = <I extends { properties: PropertySummary[] }, P>({
  propertyId,
  definitions: given,
  ...props
}: PropertiesProps<I, P> & {
  propertyId: number;
  /** Where its definition is, where not among the initiative's properties
   *  and the owner's metadata: a collection's metadata. */
  definitions?: PropertyDefinitionRead[];
}) => {
  const { t } = useTranslation(["properties", "ui"]);
  const { env } = props;
  const properties = props.saves.useShown(props.properties);
  const definition = (given ?? env?.definitions.data)?.find((each) => each.id === propertyId);
  const held = properties.find((each) => each.property_id === propertyId);
  const property = held ?? (definition ? propertyStubFromDefinition(definition) : undefined);
  // Not loaded is not deleted: an editor is told, and can ask again.
  if (!property && !given && env?.definitions.isError && !props.readOnly) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <span>{t("loadError")}</span>
        <Button
          type="button"
          variant="link"
          size="sm"
          onClick={() => void env.definitions.refetch()}
        >
          {t("ui:tryAgain")}
        </Button>
      </div>
    );
  }
  if (!property) return null;
  if (props.readOnly || !env) {
    if (isEmptyPropertyValue(property.value)) return null;
    return (
      <ReadField label={property.name}>
        <PropertyValueCell summary={property} variant="cell" updatedAt={props.updatedAt} />
      </ReadField>
    );
  }
  return <PropertyField {...props} env={env} properties={properties} property={property} placed />;
};

/** An item's custom properties, each saved on its own, and adding one. */
export const PropertiesField = <I extends { properties: PropertySummary[] }, P>({
  except,
  hideLabel = false,
  ...props
}: PropertiesProps<I, P> & {
  /** Properties the layout places on their own, which are not repeated here. */
  except?: ReadonlySet<number>;
  /** Under a heading the host draws. */
  hideLabel?: boolean;
}) => {
  const { t } = useTranslation("properties");
  const { saves, id, initiativeId, env } = props;
  const properties = saves.useShown(props.properties);
  // Its own values: a collection's metadata is the collection's, and a
  // plug-in's values are drawn as its fields.
  const listed = ownProperties(properties).filter((each) => !except?.has(each.property_id));
  // Where the item also holds its project's metadata, the panel says so.
  const label = t(props.owner ? "titleWithMetadata" : "title");
  const none = t(props.owner ? "noPropertiesOrMetadata" : "noMetadata");
  const save = saves.useSave(label);
  const add = (definition: PropertyDefinitionRead) => {
    if (properties.some((p) => p.property_id === definition.id)) return;
    void save.save({
      properties: { values: [{ property_id: definition.id, value: null }] },
      shows: {
        properties: [...properties, propertyStubFromDefinition(definition)],
      } as Partial<I>,
    });
  };
  const sorted = [...listed].sort((a, b) => a.name.localeCompare(b.name));
  // A reader sees each value as it reads anywhere else: a link opens.
  if (props.readOnly || !env) {
    return (
      <div className="space-y-2">
        {hideLabel ? null : <p className="font-medium text-sm">{label}</p>}
        {sorted.length === 0 ? (
          <p className="text-muted-foreground text-sm">{none}</p>
        ) : (
          <ul className="space-y-2">
            {sorted.map((property) => {
              const Icon = iconForPropertyType(property.type);
              return (
                <li
                  key={property.property_id}
                  className="grid grid-cols-[minmax(0,8rem)_1fr] items-center gap-2"
                >
                  <span className="flex min-w-0 items-center gap-1.5 font-normal text-muted-foreground text-xs">
                    <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="truncate">{property.name}</span>
                  </span>
                  <PropertyValueCell
                    summary={property}
                    variant="cell"
                    updatedAt={props.updatedAt}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }
  return (
    <FieldFrame label={label} save={save} hideLabel={hideLabel}>
      {sorted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{none}</p>
      ) : (
        sorted.map((property) => (
          // Keyed by the row too: a host that moves to another row starts
          // its edits afresh.
          <PropertyField
            key={`${id}:${property.property_id}`}
            {...props}
            env={env}
            properties={properties}
            property={property}
          />
        ))
      )}
      <AddPropertyButton
        definitions={env.definitions.data ?? NO_DEFINITIONS}
        loading={env.definitions.isLoading}
        initiativeId={initiativeId ?? 0}
        owner={props.owner}
        create={env.createProperty}
        currentPropertyIds={[...listed.map((p) => p.property_id), ...(except ?? [])]}
        onAdd={add}
        disabled={!initiativeId}
      />
    </FieldFrame>
  );
};
