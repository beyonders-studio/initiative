import {
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { ItemDraftContext } from "@/hooks/useFieldSave";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

/** Where one field's save stands. */
export type FieldSaveState = "idle" | "saving" | "saved" | "error";

/** What a field shows of its own save, and how to send it again. */
export interface FieldSave {
  state: FieldSaveState;
  retry: () => void;
  /** What the last save failed with. */
  error?: unknown;
}

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
  const { t } = useTranslation("common");
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

/** The answers that refuse a value, rather than fail to save it. */
const REFUSED: ReadonlySet<number> = new Set([400, 422]);

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
  const { t } = useTranslation("common");
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
      {save.state === "error" && REFUSED.has(getHttpStatus(save.error) ?? 0) ? (
        // A value the server refuses says why, so it can be put right rather
        // than tried again.
        <p className="text-destructive text-xs">{getErrorMessage(save.error)}</p>
      ) : null}
      {changed ? (
        <p role="status" className="text-muted-foreground text-xs">
          {t("fieldSave.changed")}
        </p>
      ) : null}
    </fieldset>
  );
};
