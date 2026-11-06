/**
 * Writing a statement by hand, with the registry offering the names.
 *
 * A plain textarea, because a statement here is a few lines and a code editor
 * would be a dependency and a second set of keybindings for no gain. What it
 * adds is completion: the datasets, functions and fields the server says exist,
 * offered as a word is typed and inserted only when one is chosen.
 *
 * Completion is a convenience, never a check. What may be written is decided by
 * the validator, which the caller asks on every pause — so a name this fails to
 * offer still works if it is real, and one it offers wrongly is refused with a
 * reason rather than run.
 */

import { Braces, Columns3, FileSpreadsheet, Spline, Table2, UserRound } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getCaretCoordinates } from "@/lib/caretCoordinates";
import { cn } from "@/lib/utils";
import {
  applyCompletion,
  type Completion,
  type CompletionKind,
  completionsFor,
  type DatasetFields,
  datasetsNamed,
  wordAt,
} from "@/lib/widgets/completion";

/** How many names the list offers at once. */
const LIMIT = 8;
const POPOVER_WIDTH = 280;

const ICONS: Record<CompletionKind, typeof Table2> = {
  dataset: Table2,
  field: Columns3,
  function: Braces,
  token: UserRound,
  relation: Spline,
  spreadsheet: FileSpreadsheet,
};

export interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  datasets: string[];
  functions: string[];
  fields: DatasetFields[];
  /** Names that stand for who is asking, offered beside the fields. */
  tokens?: string[];
  /** The ranges the statement read when last checked, under the names each
   *  is read under. */
  ranges?: DatasetFields[];
  /** The spreadsheets a `sheet()` call may name. */
  spreadsheets?: string[];
  id?: string;
  rows?: number;
  disabled?: boolean;
  "aria-describedby"?: string;
}

export function SqlEditor({
  value,
  onChange,
  datasets,
  functions,
  fields,
  tokens,
  ranges,
  spreadsheets,
  id,
  rows = 6,
  disabled,
  "aria-describedby": describedBy,
}: SqlEditorProps) {
  const { t } = useTranslation("dashboards");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [active, setActive] = useState<{
    word: string;
    start: number;
    caret: number;
    qualifier?: string;
    quoted?: boolean;
  } | null>(null);
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const [highlighted, setHighlighted] = useState(0);

  // Which datasets this statement already names. What may be written bare is
  // theirs, and what one of them declares a way to reach is written under that
  // relation's name — both decided in the completion module, which is where
  // the rest of the deciding already happens.
  const named = useMemo(() => datasetsNamed(value, datasets), [value, datasets]);

  const offered = useMemo(() => {
    if (!active) return [];
    return completionsFor(active.word, {
      datasets,
      functions,
      fields,
      tokens,
      named,
      qualifier: active.qualifier,
      ranges,
      spreadsheets,
      quoted: active.quoted,
    }).slice(0, LIMIT);
  }, [active, datasets, functions, fields, tokens, named, ranges, spreadsheets]);

  const close = useCallback(() => {
    setActive(null);
    setAnchor(null);
    setHighlighted(0);
  }, []);

  const sync = useCallback((textarea: HTMLTextAreaElement) => {
    const caret = textarea.selectionStart ?? 0;
    const found = wordAt(textarea.value, caret);
    if (!found) {
      setActive(null);
      setAnchor(null);
      return;
    }
    setActive({ ...found, caret });
    setHighlighted(0);
    const position = getCaretCoordinates(textarea, found.start);
    setAnchor({
      top: position.top + position.height + 4,
      left: Math.min(position.left, Math.max(0, textarea.offsetWidth - POPOVER_WIDTH)),
    });
  }, []);

  const accept = useCallback(
    (completion: Completion) => {
      const textarea = textareaRef.current;
      if (!textarea || !active) return;
      const next = applyCompletion(value, active.start, active.caret, completion);
      onChange(next.text);
      close();
      // After React has written the new value, or the caret lands in the old
      // one and the browser puts it back at the end.
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(next.caret, next.caret);
      });
    },
    [active, value, onChange, close]
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!offered.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((current) => (current + 1) % offered.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((current) => (current - 1 + offered.length) % offered.length);
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      accept(offered[highlighted]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  };

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        id={id}
        rows={rows}
        disabled={disabled}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        aria-describedby={describedBy}
        aria-label={t("builder.statement")}
        className={cn(
          "flex w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs",
          "ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50"
        )}
        value={value}
        placeholder={t("builder.statementPlaceholder")}
        onChange={(event) => {
          onChange(event.target.value);
          sync(event.target);
        }}
        onKeyDown={onKeyDown}
        onClick={(event) => sync(event.currentTarget)}
        onKeyUp={(event) => {
          // Moving the caret changes which word is being completed; typing is
          // already handled by onChange.
          if (event.key.startsWith("Arrow") || event.key === "Home" || event.key === "End") {
            sync(event.currentTarget);
          }
        }}
        onBlur={close}
      />

      {offered.length > 0 && anchor && (
        <ul
          // Keyboard-driven: the textarea keeps focus so typing continues, and
          // pointer-down is caught before the blur that would close this.
          className="absolute z-50 max-h-56 overflow-y-auto rounded-md border bg-popover p-1 shadow-md"
          style={{ top: anchor.top, left: anchor.left, width: POPOVER_WIDTH }}
          onPointerDown={(event) => event.preventDefault()}
        >
          {offered.map((completion, index) => {
            const Icon = ICONS[completion.kind];
            return (
              <li key={`${completion.kind}:${completion.name}:${completion.detail ?? ""}`}>
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-xs",
                    index === highlighted ? "bg-accent text-accent-foreground" : "text-foreground"
                  )}
                  onClick={() => accept(completion)}
                  onMouseEnter={() => setHighlighted(index)}
                >
                  <Icon className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate font-mono">{completion.name}</span>
                  {completion.detail && (
                    <span className="ml-auto shrink-0 truncate text-3xs text-muted-foreground">
                      {completion.detail}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
