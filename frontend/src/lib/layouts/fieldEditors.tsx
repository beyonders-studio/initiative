/**
 * Field editors any detail shares (a task's, an event's): the title, the
 * tags and the custom properties, each saved on its own through the save of
 * the item's kind.
 */

import { useBlocker } from "@tanstack/react-router";
import { Loader2, Sparkles, X } from "lucide-react";
import {
  type ReactNode,
  type RefObject,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  ContentKind,
  PropertyDefinitionRead,
  PropertySummary,
  TagSummary,
  Tool,
  UserSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { usePersonMention } from "@/components/comments/usePersonMention";
import { MentionComposer } from "@/components/markdown/MentionComposer";
import { AddPropertyButton } from "@/components/properties/AddPropertyButton";
import { PropertyInput } from "@/components/properties/PropertyInput";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import {
  isEmptyPropertyValue,
  normalizePropertyValue,
  propertyStubFromDefinition,
  userReferenceValue,
} from "@/components/properties/propertyHelpers";
import { iconForPropertyType } from "@/components/properties/propertyTypeIcons";
import { SubscribeButton } from "@/components/SubscribeButton";
import { TagPicker } from "@/components/tags";
import { TagBadgeList } from "@/components/tags/TagBadge";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Textarea } from "@/components/ui/textarea";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import {
  type FieldSaveKind,
  type FieldSaveOptions,
  ItemDraftContext,
  type ItemEdit,
  type ItemFieldSave,
  useHeldItem,
  useItemFieldSave,
} from "@/hooks/useFieldSave";
import { usePastedImages } from "@/hooks/usePastedImages";
import { useProperties } from "@/hooks/useProperties";
import type { MemberSearchScope } from "@/hooks/useUsers";
import { getHttpStatus } from "@/lib/errorMessage";
import { currentServerKey } from "@/lib/offlineSession";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { cn } from "@/lib/utils";

import { FieldFrame, ReadField, sameJson, useFieldDraft } from "./editing";

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

/** An item's title, which is its detail's heading, saved as `field` (a queue
 *  item's is its `label`). It cannot be emptied: leaving it blank puts the
 *  saved one back. A reader who cannot change it sees the heading alone. */
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

export const TitleField = <I, P>({
  id,
  label,
  value,
  save,
  readOnly,
  placeholder,
  field = "title",
  optional = false,
  subscribe,
  marks,
  below,
  mention,
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
  /** The item, for a subscribe toggle beside its title. */
  subscribe?: { kind: ContentKind; id: number };
  /** Stretches of the title drawn marked, each with its own class. */
  marks?: readonly { start: number; end: number; className: string }[];
  /** Drawn under the title, inside its frame. */
  below?: ReactNode;
  /** `@` offers these people, and writes the picked one's handle. */
  mention?: { members: MemberSearchScope; onPick?: (member: UserSummary) => void };
}) => {
  // One being added may be emptied while it is typed: Add waits for a title.
  const adding = useContext(ItemDraftContext) !== null;
  const besides = (title: ReactNode) =>
    subscribe && !adding ? (
      <div className="flex min-w-0 grow basis-72 items-start gap-1">
        {title}
        <SubscribeButton kind={subscribe.kind} entityId={subscribe.id} className="mt-0.5" />
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
  const people = usePersonMention({
    field: box,
    text: draft.value,
    onChange: draft.change,
    members: mention?.members ?? { type: "community" },
    enabled: mention !== undefined && !readOnly,
    onPick: mention?.onPick,
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
      <div className="relative">
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
            people.sync(event.target, text);
          }}
          {...people.handlers}
          // A list open under the field takes Escape for itself.
          data-picking={people.open || undefined}
          placeholder={placeholder}
          className={cn(
            TITLE_TEXT,
            "relative min-h-0 resize-none shadow-none focus-visible:ring-0"
          )}
        />
        {people.popover}
      </div>
      {below}
    </FieldFrame>
  );
};

/** An item's tags, saved the moment they are picked. Clearing them offers
 *  Undo. A reader who cannot change them sees the tags alone, and nothing
 *  where there are none. */
export const TagsField = <
  I extends { tags: TagSummary[] },
  P extends { tag_ids?: number[] | null },
>({
  label,
  tags,
  save,
  readOnly,
  placeholder,
}: {
  label: string;
  tags: TagSummary[];
  save: ItemFieldSave<I, P>;
  readOnly: boolean;
  placeholder: string;
}) => {
  const edit = (picked: TagSummary[]): ItemEdit<I, P> => ({
    patch: { tag_ids: picked.map((tag) => tag.id) } as P,
    shows: { tags: picked } as Partial<I>,
  });
  if (readOnly) {
    return tags.length ? (
      <div className="space-y-2">
        <p className="font-medium text-sm">{label}</p>
        <TagBadgeList tags={tags} limit={tags.length} className="gap-2" />
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <TagPicker
        selectedTags={tags}
        onChange={(picked) =>
          void save.save(edit(picked), picked.length === 0 ? edit(tags) : undefined)
        }
        placeholder={placeholder}
      />
    </FieldFrame>
  );
};

/** What the properties of an item take: its kind's save, the item, and who
 *  a person-valued property may name. */
type PropertiesProps<I extends { properties: PropertySummary[] }, P> = {
  kind: FieldSaveKind<I, P>;
  id: number;
  properties: PropertySummary[];
  readOnly: boolean;
  initiativeId: number | null;
  /** Whose people a person-valued property may name: who can open this tool. */
  canOpen: { tool: Tool; id: number | null | undefined };
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
  kind,
  id,
  properties,
  readOnly,
  initiativeId,
  canOpen,
  property,
  placed = false,
}: PropertiesProps<I, P> & {
  property: PropertySummary;
  /** Placed on the layout on its own: it stays when emptied, so its button
   *  clears its value (a checkbox has no empty to click back to) rather than
   *  taking it off the item. */
  placed?: boolean;
}) => {
  const { t } = useTranslation(["properties", "common"]);
  const save = useItemFieldSave(kind, id, property.name);
  const saved = normalizePropertyValue(property);
  const edit = (value: unknown): ItemEdit<I, P> => ({
    properties: { values: [{ property_id: property.property_id, value }] },
    shows: { properties: withValue(properties, property, value) } as Partial<I>,
  });
  const draft = useFieldDraft(
    saved,
    (value) =>
      save.save(
        edit(value),
        isEmptyPropertyValue(value) && !isEmptyPropertyValue(saved) ? edit(saved) : undefined
      ),
    sameJson
  );
  // The property stays until it is gone, so a failed removal says so here.
  const remove = () => {
    draft.restore();
    void save.save(
      { properties: { values: [], removed: [property.property_id] }, shows: {} },
      { ...edit(saved), shows: { properties } as Partial<I> }
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
            aria-label={placed ? t("common:clear") : t("remove")}
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
        disabled={readOnly}
        initiativeId={initiativeId}
        canOpen={canOpen}
        selectedUser={userReferenceValue(property)}
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
        className="h-9"
      />
    </FieldFrame>
  );
};

/** An item's custom properties, each saved on its own, and adding one. */
/**
 * One property placed on the layout on its own: drawn whether or not the item
 * has a value for it yet, and saved on its own. A reader sees it only where it
 * holds a value; a property since deleted draws nothing.
 */
export const PlacedPropertyField = <I extends { properties: PropertySummary[] }, P>({
  propertyId,
  ...props
}: PropertiesProps<I, P> & { propertyId: number }) => {
  const { t } = useTranslation(["properties", "common"]);
  const definitions = useProperties({
    initiativeId: props.initiativeId ?? undefined,
    enabled: props.initiativeId !== null,
  });
  const definition = definitions.data?.find((each) => each.id === propertyId);
  const held = props.properties.find((each) => each.property_id === propertyId);
  const property = held ?? (definition ? propertyStubFromDefinition(definition) : undefined);
  // Not loaded is not deleted: an editor is told, and can ask again.
  if (!property && definitions.isError && !props.readOnly) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <span>{t("loadError")}</span>
        <Button type="button" variant="link" size="sm" onClick={() => void definitions.refetch()}>
          {t("common:tryAgain")}
        </Button>
      </div>
    );
  }
  if (!property) return null;
  if (props.readOnly) {
    if (isEmptyPropertyValue(property.value)) return null;
    return (
      <ReadField label={property.name}>
        <PropertyValueCell summary={property} variant="cell" />
      </ReadField>
    );
  }
  return <PropertyField {...props} property={property} placed />;
};

/** One holder per read of a row's properties, so a copy passed again is the
 *  same copy ({@link useHeldItem}). */
const holders = new WeakMap<PropertySummary[], { properties: PropertySummary[] }>();
const holderOf = (properties: PropertySummary[]) => {
  let holder = holders.get(properties);
  if (!holder) {
    holder = { properties };
    holders.set(properties, holder);
  }
  return holder;
};

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
  const { kind, id, readOnly, initiativeId } = props;
  const { properties } = useHeldItem(
    kind as unknown as FieldSaveKind<{ properties: PropertySummary[] }, P>,
    id,
    holderOf(props.properties)
  );
  const listed = except ? properties.filter((each) => !except.has(each.property_id)) : properties;
  const label = t("title");
  const save = useItemFieldSave(kind, id, label);
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
  if (readOnly) {
    return (
      <div className="space-y-2">
        {hideLabel ? null : <p className="font-medium text-sm">{label}</p>}
        {sorted.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
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
                  <PropertyValueCell summary={property} variant="cell" />
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
        <p className="text-muted-foreground text-sm">{t("noProperties")}</p>
      ) : (
        sorted.map((property) => (
          // Keyed by the row too: a host that moves to another row starts
          // its edits afresh.
          <PropertyField
            key={`${id}:${property.property_id}`}
            {...props}
            properties={properties}
            property={property}
          />
        ))
      )}
      <AddPropertyButton
        initiativeId={initiativeId ?? 0}
        currentPropertyIds={[...listed.map((p) => p.property_id), ...(except ?? [])]}
        onAdd={add}
        disabled={readOnly || !initiativeId}
      />
    </FieldFrame>
  );
};

/** A description being written, and the one it was written over. */
interface DescriptionDraft {
  text: string;
  base: string | null;
}

const readDescriptionDraft = (key: string): DescriptionDraft | null => {
  try {
    const stored = JSON.parse(getItem(key) ?? "null") as DescriptionDraft | null;
    return stored && typeof stored.text === "string" ? stored : null;
  } catch {
    return null;
  }
};

/** The preview of a description being edited reads the way the saved one will. */
const renderDescription = (draft: string, onChange?: (draft: string) => void) => (
  <TaskDescription content={draft} onChange={onChange} />
);

/**
 * An item's description, in a composer that opens on its preview, saved only
 * with Save (or Ctrl/Cmd+Enter). What is typed is a draft, kept on the device
 * until it is saved or discarded. The save names the description it was
 * written over, and one written over a description that has since changed is
 * refused, so the reader sees the other version and chooses.
 */
export const DescriptionField = <I, P>({
  field = "description",
  kind,
  id,
  options,
  label,
  htmlId,
  value,
  readOnly,
  preview = false,
  initiativeId,
  subject,
  leaving,
  placeholder,
  suggest,
  maxLength,
}: {
  /** What the item calls it (a queue item's `notes`). A save names the text
   *  it was written over as `<field>_base`, which the server refuses once
   *  that has changed. */
  field?: string;
  kind: FieldSaveKind<I, P>;
  id: number;
  /** What the detail adds to its saves. */
  options: FieldSaveOptions<I, P>;
  label: string;
  htmlId: string;
  /** The description as saved. */
  value: string | null;
  readOnly: boolean;
  /** Drawn in the layout editor, where nothing is changed: a draft kept on
   *  the device stays there. */
  preview?: boolean;
  initiativeId: number | null;
  /** The item, as its references name it. */
  subject: string;
  /** Set when the page is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  placeholder: string;
  /** Writes a description for the reader to start from (AI). */
  suggest?: { label: string; run: () => Promise<string> };
  /** The most characters it may hold, as the server allows. */
  maxLength?: number;
}) => {
  const { t } = useTranslation("common");
  const communityId = useActiveCommunityId();
  const { user } = useAuth();
  const uploadImage = usePastedImages();
  // Saved by Save or by Retry. What was typed while it saved stays the draft,
  // now written over the description just saved.
  const save = useItemFieldSave(kind, id, label, {
    ...options,
    onSaved: (edit) => {
      options.onSaved?.(edit);
      const now = latest.current;
      const saved = ((edit.shows as Record<string, unknown>)[field] as string | null) ?? null;
      if (now) setDraft(now.text === (saved ?? "") ? null : { ...now, base: saved });
    },
  });
  // Each account on each server keeps its own drafts on a shared device.
  const key = `${kind.name}-${field}-draft:${user?.id}@${currentServerKey()}:${communityId}:${id}`;
  const [draft, setDraftState] = useState(() => readDescriptionDraft(key));
  const [discarding, setDiscarding] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  // The written description, and the draft it replaced, for Undo suggestion.
  const [suggested, setSuggested] = useState<{
    text: string;
    before: DescriptionDraft | null;
  } | null>(null);
  // Read by the description written for the reader, which lands later.
  const latest = useRef(draft);

  const setDraft = (next: DescriptionDraft | null) => {
    latest.current = next;
    setDraftState(next);
    void (next ? setItem(key, JSON.stringify(next)) : removeItem(key));
    // A refused save belongs to the draft, and goes with it.
    if (!next) save.reset();
  };

  const current = value ?? "";
  // One being added is written straight into it: nothing is saved until Add.
  const adding = useContext(ItemDraftContext) !== null;
  const write = (text: string) =>
    void save.save({
      patch: { [field]: text || null } as P,
      shows: { [field]: text || null } as Partial<I>,
    });
  // A reader who can no longer edit keeps the draft on the device, but sees
  // the saved description and nothing that would write.
  const open = readOnly || preview || adding ? null : draft;
  const conflict = open !== null && getHttpStatus(save.error) === 409;
  const dirty = open !== null && open.text !== (open.base ?? "");
  const blocker = useBlocker({
    shouldBlockFn: () => dirty && !leaving.current,
    enableBeforeUnload: () => dirty && !leaving.current,
    withResolver: true,
  });

  const submit = (base: string | null) => {
    if (!open) return;
    const description = open.text || null;
    void save.save({
      patch: { [field]: description, [`${field}_base`]: base } as P,
      shows: { [field]: description } as Partial<I>,
    });
  };
  const cancel = () => (dirty ? setDiscarding(true) : setDraft(null));
  const startFrom = async () => {
    if (!suggest) return;
    setSuggesting(true);
    try {
      const text = await suggest.run();
      setSuggested({ text, before: latest.current });
      setDraft({ text, base: latest.current?.base ?? value });
    } catch {
      // The request says what went wrong.
    } finally {
      setSuggesting(false);
    }
  };

  return (
    <FieldFrame
      label={label}
      htmlFor={htmlId}
      // The conflict below says what went wrong, and Retry would only repeat it.
      save={conflict ? { ...save, state: "idle" } : save}
      changed={
        open !== null && !conflict && save.state !== "saving" && current !== (open.base ?? "")
      }
    >
      {readOnly ? (
        <>
          {current ? (
            <div className="rounded-md border border-border/70 border-dashed bg-muted/40 px-3 py-2">
              <TaskDescription content={current} />
            </div>
          ) : (
            <p className="text-muted-foreground text-sm italic">{t("descriptionField.none")}</p>
          )}
          {draft !== null ? (
            <p className="text-muted-foreground text-xs">{t("descriptionField.draftKept")}</p>
          ) : null}
        </>
      ) : (
        <div className="space-y-2">
          <MentionComposer
            id={htmlId}
            value={open?.text ?? current}
            onChange={(text) =>
              adding ? write(text) : setDraft({ text, base: open ? open.base : value })
            }
            initiativeId={initiativeId ?? 0}
            subject={subject}
            renderPreview={renderDescription}
            onUploadImage={uploadImage}
            defaultMode="preview"
            placeholder={placeholder}
            maxLength={maxLength}
            onKeyDown={(event) => {
              if (!open) return;
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit(open.base);
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
            actions={
              suggest ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  onClick={() => void startFrom()}
                  disabled={suggesting}
                >
                  {suggesting ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  {suggest.label}
                </Button>
              ) : null
            }
          />
          {open === null ? null : conflict ? (
            <div
              role="alert"
              className="space-y-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2"
            >
              <p className="text-sm">{t("fieldSave.changed")}</p>
              <div className="rounded-md border bg-background px-3 py-2">
                <TaskDescription content={current} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => submit(value)}>
                  {t("fieldSave.overwrite")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    save.reset();
                    setDraft({ ...open, base: value });
                  }}
                >
                  {t("fieldSave.keepEditing")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={save.state === "saving"}
                onClick={() => submit(open.base)}
              >
                {t("save")}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={cancel}>
                {t("cancel")}
              </Button>
              {suggested !== null && open.text === suggested.text ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setDraft(suggested.before);
                    setSuggested(null);
                  }}
                >
                  {t("descriptionField.undoSuggestion")}
                </Button>
              ) : null}
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("descriptionField.unsavedTitle")}
        confirmLabel={t("fieldSave.discard")}
        cancelLabel={t("fieldSave.keepEditing")}
        onConfirm={() => {
          setDiscarding(false);
          setDraft(null);
        }}
        destructive
      />
      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(isOpen) => {
          if (!isOpen) blocker.reset?.();
        }}
        title={t("descriptionField.unsavedTitle")}
        description={t("descriptionField.unsavedBody")}
        confirmLabel={t("descriptionField.leave")}
        cancelLabel={t("descriptionField.stay")}
        onConfirm={() => {
          setDraft(null);
          blocker.proceed?.();
        }}
        destructive
      />
    </FieldFrame>
  );
};
