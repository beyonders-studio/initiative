import { useLayoutEffect, useSyncExternalStore } from "react";

import { isFormula } from "@/lib/spreadsheet/formula";
import { extractReferences, type FormulaRefToken } from "@/lib/spreadsheet/formula-refs";

const NO_TOKENS: FormulaRefToken[] = [];

/** The cells a set of references covers, and in which colors — what the grid
 *  draws, leaving out where each reference sits in the text. */
const boxKey = (tokens: FormulaRefToken[]): string =>
  tokens.map((t) => `${t.sheet ?? ""}!${t.r1}:${t.c1}:${t.r2}:${t.c2}:${t.colorIndex}`).join("|");

/**
 * The text of the cell being edited, held outside React state.
 *
 * A keystroke changes only this text, and only the two inputs that show it —
 * the cell's own and the formula bar — subscribe to it. The editor around
 * them reads ``boxes``, which keeps its identity until a reference is added,
 * removed or moved, so typing redraws two inputs rather than the grid.
 */
export interface DraftStore {
  get: () => string;
  /** The references in the draft, when it is a formula. */
  tokens: () => FormulaRefToken[];
  /** ``tokens`` as of the last change to the cells they cover. Their text
   *  offsets can be out of date; read only their cells and colors. */
  boxes: () => FormulaRefToken[];
  /** Replace the draft. ``caret`` is placed in ``input`` once the new text
   *  is on screen: the input is controlled, so a caret set earlier would be
   *  reset by the render that shows the text. */
  set: (draft: string, caret?: CaretRequest) => void;
  /** Place the caret ``set`` asked for, if it hasn't been yet. */
  applyCaret: () => void;
  subscribe: (listener: () => void) => () => void;
}

interface CaretRequest {
  input: HTMLInputElement;
  at: number;
}

export const createDraftStore = (): DraftStore => {
  let draft = "";
  let tokens = NO_TOKENS;
  let boxes = NO_TOKENS;
  let boxesKey = "";
  let caret: CaretRequest | null = null;
  const listeners = new Set<() => void>();

  const applyCaret = () => {
    if (!caret) return;
    const { input, at } = caret;
    caret = null;
    input.focus();
    input.setSelectionRange(at, at);
  };

  return {
    get: () => draft,
    tokens: () => tokens,
    boxes: () => boxes,
    set: (next, request) => {
      caret = request ?? null;
      if (next === draft) {
        // Nothing will re-render, so nothing would place the caret later.
        applyCaret();
        return;
      }
      draft = next;
      tokens = isFormula(next) ? extractReferences(next) : NO_TOKENS;
      const key = boxKey(tokens);
      if (key !== boxesKey) {
        boxesKey = key;
        boxes = tokens;
      }
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    applyCaret,
  };
};

/** The draft and its references, for an input that shows it. */
export const useDraft = (store: DraftStore) => {
  const value = useSyncExternalStore(store.subscribe, store.get);
  const tokens = useSyncExternalStore(store.subscribe, store.tokens);
  // Every subscriber's DOM is updated before any layout effect runs, so the
  // first input to get here can place the caret in whichever one asked.
  useLayoutEffect(() => store.applyCaret(), [store, value]);
  return { value, tokens };
};
