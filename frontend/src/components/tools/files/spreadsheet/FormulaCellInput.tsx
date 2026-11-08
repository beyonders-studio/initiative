import { type FocusEvent, type KeyboardEvent, type Ref, useMemo, useRef } from "react";

import { FORMULA_REF_COLORS, type FormulaRefToken } from "@/lib/spreadsheet/formula-refs";

interface FormulaCellInputProps {
  value: string;
  /** References found in ``value`` — drive the colored text segments. */
  tokens: FormulaRefToken[];
  /** Accepts a callback ref as readily as an object one: the in-cell
   *  editor focuses itself the moment it attaches, which is not the same
   *  moment the edit began. */
  inputRef: Ref<HTMLInputElement> | null;
  onChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  /** Receives the blur event so the caller can inspect ``relatedTarget`` (a
   *  focus handoff between the in-cell and formula-bar editors must not
   *  commit the edit). */
  onBlur: (e: FocusEvent<HTMLInputElement>) => void;
  /** Fired when this input gains focus — lets the editor track which of the
   *  two editing surfaces (cell vs formula bar) point-mode should target. */
  onFocus?: () => void;
  /** Accessible label for the input — set for the standalone formula bar; the
   *  in-cell editor inherits the grid's labelling and leaves it undefined. */
  ariaLabel?: string;
}

/**
 * The in-cell editor for a spreadsheet cell. A single-line ``<input>`` can't
 * render colored runs, so the real (transparent-text) input sits on top of a
 * mirror div that paints each reference token in its highlight color — Excel's
 * formula-bar coloring. The caret stays visible; horizontal scroll is kept in
 * sync so long formulas stay aligned. With no tokens (a plain value, or a
 * non-formula draft) the mirror is just the plain text, so behavior is
 * unchanged — and the component is rendered for every edit so typing the
 * leading "=" never remounts the input and drops focus.
 */
export const FormulaCellInput = ({
  value,
  tokens,
  inputRef,
  onChange,
  onKeyDown,
  onBlur,
  onFocus,
  ariaLabel,
}: FormulaCellInputProps) => {
  const mirrorRef = useRef<HTMLDivElement>(null);

  const segments = useMemo(() => {
    const out: Array<{ text: string; color: string | null }> = [];
    let pos = 0;
    for (const t of tokens) {
      if (t.start > pos) out.push({ text: value.slice(pos, t.start), color: null });
      out.push({
        text: value.slice(t.start, t.end),
        color: FORMULA_REF_COLORS[t.colorIndex % FORMULA_REF_COLORS.length],
      });
      pos = t.end;
    }
    if (pos < value.length) out.push({ text: value.slice(pos), color: null });
    return out;
  }, [value, tokens]);

  return (
    <div className="relative h-full w-full bg-background">
      <div
        ref={mirrorRef}
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center overflow-hidden whitespace-pre px-1.5"
      >
        {segments.map((s, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: positional text segments, no stable id
          <span key={i} style={s.color ? { color: s.color } : undefined}>
            {s.text}
          </span>
        ))}
      </div>
      <input
        ref={inputRef}
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={onBlur}
        onFocus={onFocus}
        onScroll={(e) => {
          if (mirrorRef.current) mirrorRef.current.scrollLeft = e.currentTarget.scrollLeft;
        }}
        // ``font: inherit`` so the input matches the cell's font size/weight
        // (inputs don't inherit font by default) — both layers then track the
        // container's text-sm default and any per-cell font-size override,
        // keeping the colored mirror aligned with the typed text.
        style={{ font: "inherit" }}
        className="relative z-[1] h-full w-full select-text bg-transparent px-1.5 text-transparent caret-foreground outline-none"
      />
    </div>
  );
};
