import {
  createContext,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyStep,
  PropertySummary,
  PropertyValueInput,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

/** Where one field's save stands. */
export type FieldSaveState = "idle" | "saving" | "saved" | "error";

/** What a field shows of its own save, and how to send it again. */
export interface FieldSave {
  state: FieldSaveState;
  retry: () => void;
  /** Why the value the last save sent was refused, where it was refused
   *  rather than failed to save: said under the field, so it can be put
   *  right rather than tried again. */
  refused?: string;
}

/** A change to some of an item's fields: what is sent, and how the item reads
 *  once it is saved. A change to its properties names only those it sets,
 *  takes off or steps, so one person's leaves another's standing. */
export type ItemEdit<I, P> = { shows: Partial<I> } & (
  | { patch: P }
  | {
      properties: { values: PropertyValueInput[]; removed?: number[]; steps?: PropertyStep[] };
    }
);

/** One field's save, and how a change is sent: `undo`, where given, is the
 *  change that puts it back. Settles true once the change is saved. */
export interface ItemFieldSave<I, P> extends FieldSave {
  save: (edit: ItemEdit<I, P>, undo?: ItemEdit<I, P>) => Promise<boolean>;
}

/**
 * An item being added, which nothing has saved yet: its fields' saves change
 * the copy the dialog holds, and Add makes it whole.
 */
export interface ItemDraft {
  /** Takes in one field's change. */
  edit: (edit: ItemEdit<unknown, unknown>) => void;
  /** Adds it, as Enter in a typed field does. */
  submit: () => void;
  /** Whether the field `id` shows a value it cannot take (a number left
   *  empty), which Add waits for. */
  hold: (id: string, holding: boolean) => void;
  /** The fields changed so far, as Add sends them. */
  sent: () => Record<string, unknown>;
}

export const ItemDraftContext = createContext<ItemDraft | null>(null);

type DraftItem = { id: number; properties: PropertySummary[] };

/** An item changed field by field with nothing saved, as it is sent: as it is
 *  drawn, the fields changed on it, and the properties it is given. */
export interface Written<I, P> {
  item: I;
  fields: Partial<P>;
  properties: PropertyValueInput[];
}

/** What a draft holds as its last change left it: read by a handler that can
 *  run in the same event as the change it follows (leaving a field, or Enter
 *  in it), before the render that shows it. */
interface Held<I, P> {
  item: I;
  fields: Partial<P>;
  values: Map<number, unknown>;
  holding: Set<string>;
}

/**
 * An item changed field by field with nothing saved: an item being added, or
 * the fields a change of one asks for. Its fields' saves write into `draft`
 * (as `ItemDraftContext`); `written()` is what it holds, as it is sent.
 */
export const useItemDraft = <I extends DraftItem, P>(
  blank: I,
  { onEdit, onSubmit }: { onEdit?: () => void; onSubmit: () => void }
) => {
  const [item, setItem] = useState(blank);
  // The fields showing a value they cannot take, which sending waits for.
  const [holding, setHolding] = useState<ReadonlySet<string>>(new Set());
  const latest = useRef<Held<I, P>>({
    item,
    fields: {},
    values: new Map(),
    holding: new Set(),
  });
  const handlers = useRef({ onEdit, onSubmit });
  handlers.current = { onEdit, onSubmit };
  const draft = useMemo<ItemDraft>(
    () => ({
      edit: (edit: ItemEdit<unknown, unknown>) => {
        handlers.current.onEdit?.();
        const held = latest.current;
        held.item = { ...held.item, ...(edit.shows as Partial<I>) };
        if ("patch" in edit) {
          held.fields = { ...held.fields, ...(edit.patch as Partial<P>) };
        } else {
          for (const { property_id, value } of edit.properties.values) {
            held.values.set(property_id, value);
          }
          // A property taken off shows as gone: nothing reads it back.
          const removed = edit.properties.removed ?? [];
          for (const id of removed) held.values.delete(id);
          held.item = {
            ...held.item,
            properties: held.item.properties.filter((each) => !removed.includes(each.property_id)),
          };
        }
        setItem(held.item);
      },
      submit: () => handlers.current.onSubmit(),
      hold: (id: string, holds: boolean) => {
        const held = latest.current.holding;
        if (held.has(id) === holds) return;
        if (holds) held.add(id);
        else held.delete(id);
        setHolding(new Set(held));
      },
      sent: () => latest.current.fields as Record<string, unknown>,
    }),
    []
  );
  /** What it holds now, as it is sent. A description is named with what it
   *  was written over, so a change of an item that exists is refused where
   *  somebody else wrote it meanwhile. */
  const written = (): Written<I, P> => {
    const { item: now, fields, values } = latest.current;
    return {
      item: now,
      fields,
      properties: [...values].map(([property_id, value]) => ({ property_id, value })),
    };
  };
  return { item, holding, latest, draft, written };
};

// The inputs a value is typed into, as against picked with. A combobox's
// search box is typed into too, but what it changes is a pick.
const TYPED_INPUTS = new Set([
  "text",
  "number",
  "url",
  "email",
  "search",
  "tel",
  "date",
  "time",
  "datetime-local",
]);

/** Whether an element is one a value is typed into. */
export const isTyping = (element: EventTarget | null): boolean =>
  element instanceof HTMLTextAreaElement ||
  (element instanceof HTMLInputElement &&
    TYPED_INPUTS.has(element.type) &&
    element.getAttribute("role") !== "combobox");

interface Draft<V> {
  value: V;
  /** The saved value when the change began. */
  from: V;
  saving: boolean;
}

export interface FieldDraft<V> {
  /** What the field shows: the change in progress, or the saved value. */
  value: V;
  /** Hold a typed change until Enter or leaving the field. */
  change: (value: V) => void;
  /** Save what is held, when it differs from the saved value. */
  finish: () => void;
  /** Put the saved value back. */
  restore: () => void;
  /** A change from the field's editor: a pick saves at once, typing waits. */
  edit: (value: V) => void;
  /** The saved value moved while this one was being changed. */
  changed: boolean;
  /** For the element around the editor: Enter in a typed input or leaving it
   *  saves, and Esc puts the saved value back. */
  keys: {
    onBlur: (event: FocusEvent) => void;
    onKeyDown: (event: KeyboardEvent) => void;
  };
}

/** Whether two values read the same, as a field compares its draft. */
export const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Whether two id lists name the same ids, in any order. */
export const sameIds = (a: number[], b: number[]) => sameJson([...a].sort(), [...b].sort());

/**
 * One field's value while it is being changed, saved by the kind of change:
 * a pick the moment it is made, typing on Enter or on leaving the field.
 *
 * What was saved stays shown until the save settles, so the field never shows
 * the old value in between; anything typed meanwhile is kept. A save that
 * fails puts the saved value back, and the field says so.
 *
 * @param saved The value as the item has it now.
 * @param commit Saves a value, settling when the save does. It is given the
 *   saved value the change began from, for a save that names what it was
 *   written over.
 * @param same When a value is not compared by identity.
 * @param valid Held back from saving while false, as dates the wrong way round.
 */
export const useFieldDraft = <V,>(
  saved: V,
  commit: (value: V, from: V) => Promise<unknown>,
  same: (a: V, b: V) => boolean = Object.is,
  valid: (value: V) => boolean = () => true
): FieldDraft<V> => {
  const drafting = useContext(ItemDraftContext);
  const id = useId();
  const [draft, setDraft] = useState<Draft<V> | null>(null);
  // Read by the handlers rather than the render, as two can run in one event:
  // a picker that commits on Enter, then the Enter itself.
  const held = useRef(draft);
  const set = (next: Draft<V> | null) => {
    held.current = next;
    setDraft(next);
  };

  const change = (value: V) => {
    const current = held.current;
    const from = current && !current.saving ? current.from : saved;
    set({ value, from, saving: false });
    // An item being added takes each change as it is made, and is not added
    // while one it cannot take is shown.
    if (drafting) {
      const fits = valid(value);
      drafting.hold(id, !fits);
      if (fits) void commit(value, from);
    }
  };
  const restore = () => {
    set(null);
    drafting?.hold(id, false);
  };
  const finish = () => {
    const current = held.current;
    // An item being added took each change as it was made, and keeps showing
    // it: what it shows of a change may be nothing until it is made.
    if (drafting) return;
    if (!current || current.saving || !valid(current.value)) return;
    if (same(current.value, saved)) {
      restore();
      return;
    }
    const saving = { ...current, saving: true };
    set(saving);
    void commit(current.value, current.from).finally(() => {
      if (held.current === saving) set(null);
    });
  };
  // Leaving with a change not yet sent (Back while still typing) sends it,
  // as a blur would have.
  const leaving = useRef(finish);
  leaving.current = finish;
  useEffect(() => () => leaving.current(), []);
  useEffect(() => () => drafting?.hold(id, false), [drafting, id]);

  return {
    value: draft ? draft.value : saved,
    change,
    finish,
    restore,
    edit: (value) => {
      change(value);
      if (!isTyping(document.activeElement)) finish();
    },
    changed: !drafting && draft !== null && !draft.saving && !same(draft.from, saved),
    keys: {
      onBlur: (event) => {
        if (isTyping(event.target)) finish();
      },
      onKeyDown: (event) => {
        if (!isTyping(event.target)) return;
        // A textarea marked single-line (a title that wraps) saves on Enter too.
        const multiline =
          event.target instanceof HTMLTextAreaElement &&
          event.target.getAttribute("aria-multiline") !== "false";
        if (event.key === "Enter" && !multiline) {
          event.preventDefault();
          finish();
          drafting?.submit();
        } else if (event.key === "Escape") {
          restore();
        }
      },
    },
  };
};

const FieldSaveStatus = ({ save }: { save: FieldSave }) => {
  const { t } = useTranslation("ui");
  if (save.state === "error") {
    return (
      <span
        role="alert"
        className="ml-auto inline-flex items-center gap-1 text-destructive text-xs"
      >
        {t("fieldSave.failed")}
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs"
          onClick={save.retry}
        >
          {t("tryAgain")}
        </Button>
      </span>
    );
  }
  return (
    <span role="status" className="ml-auto text-muted-foreground text-xs">
      {save.state === "saving" ? t("fieldSave.saving") : null}
      {save.state === "saved" ? t("fieldSave.saved") : null}
    </span>
  );
};

/** A field as a reader reads it: its label, then its value. */
export const ReadField = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="space-y-1">
    <p className="font-medium text-sm">{label}</p>
    {children}
  </div>
);

/**
 * One field on a detail: its label, its own save state with Retry, a
 * note when it changed underneath an edit, and the editor.
 *
 * A field whose label is hidden has no row for its save state, so the state
 * floats instead, where it moves nothing: level with the top of the editor
 * (beside a label the editor draws itself), or just under it.
 */
export const FieldFrame = ({
  label,
  htmlFor,
  save,
  changed = false,
  keys,
  hideLabel = false,
  statusBelow = false,
  action,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  save: FieldSave;
  changed?: boolean;
  keys?: FieldDraft<unknown>["keys"];
  hideLabel?: boolean;
  /** With the label hidden, the save state sits under the editor. */
  statusBelow?: boolean;
  /** Beside the label. */
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) => {
  const { t } = useTranslation("ui");
  return (
    <fieldset aria-label={label} className={cn("relative min-w-0 space-y-2", className)} {...keys}>
      {hideLabel ? (
        <>
          <Label htmlFor={htmlFor} className="sr-only">
            {label}
          </Label>
          <div
            className={cn(
              "absolute right-0 flex h-5 items-center",
              statusBelow ? "top-full mt-2" : "-top-0.5"
            )}
          >
            <FieldSaveStatus save={save} />
          </div>
        </>
      ) : (
        <div className="flex min-h-5 items-center gap-2">
          <Label htmlFor={htmlFor}>{label}</Label>
          {action}
          <FieldSaveStatus save={save} />
        </div>
      )}
      {children}
      {save.state === "error" && save.refused ? (
        <p className="text-destructive text-xs">{save.refused}</p>
      ) : null}
      {changed ? (
        <p role="status" className="text-muted-foreground text-xs">
          {t("fieldSave.changed")}
        </p>
      ) : null}
    </fieldset>
  );
};
