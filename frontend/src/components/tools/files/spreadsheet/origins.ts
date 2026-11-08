/**
 * Every Yjs transaction origin the spreadsheet writes under, in one place.
 *
 * An origin is how a write says what it was. `Y.UndoManager` tracks a
 * transaction only when its origin is one it was told about, so an origin and
 * its undoability are the same decision — and they are made here, together,
 * rather than in a list kept alongside the call sites.
 *
 * **Nesting.** Yjs flattens nested `transact` calls and keeps only the
 * *outermost* origin. An action that wraps several store mutations in an outer
 * `doc.transact(fn, origin)` is therefore seen as that outer origin alone; the
 * inner ones never surface. Pasting a block is the case to remember: it writes
 * cells, clears a cut's source and replaces formatting through three different
 * stores, and the whole thing reaches the undo stack as {@link PASTE}.
 */

/**
 * Origins that record something a person did. Every one of these is undoable,
 * and one press of undo reverses exactly one of them.
 */
export const SPREADSHEET_ORIGINS = {
  EDIT: "spreadsheet-edit",
  BULK: "spreadsheet-bulk",
  REPLACE_ALL: "spreadsheet-replace-all",
  PASTE: "spreadsheet-paste",
  IMPORT: "spreadsheet-import",
  FMT_EDIT: "spreadsheet-fmt-edit",
  FMT_BATCH: "spreadsheet-fmt-batch",
  FMT_REPLACE_ALL: "spreadsheet-fmt-replace-all",
  SORT: "spreadsheet-sort",
  STRUCTURE: "spreadsheet-structure",
  SHEET_ADD: "spreadsheet-sheet-add",
  SHEET_RENAME: "spreadsheet-sheet-rename",
  SHEET_DELETE: "spreadsheet-sheet-delete",
  SHEET_MOVE: "spreadsheet-sheet-move",
  SHEET_DUPLICATE: "spreadsheet-sheet-duplicate",
  SHEET_HIDDEN: "spreadsheet-sheet-hidden",
} as const;

/**
 * Origins that bring a file into being rather than change one. Undo never
 * reaches these: hydrating a doc is not an edit a reader made, and rolling it
 * back would empty the sheet.
 */
export const SPREADSHEET_SEED_ORIGINS = {
  BOOTSTRAP: "spreadsheet-bootstrap",
} as const;

/** What `Y.UndoManager` is told to track — the registry above, entire. */
export const UNDOABLE_SPREADSHEET_ORIGINS: readonly string[] = Object.values(SPREADSHEET_ORIGINS);

/** Every origin the spreadsheet may write under, undoable or not. */
export const ALL_SPREADSHEET_ORIGINS: readonly string[] = [
  ...Object.values(SPREADSHEET_ORIGINS),
  ...Object.values(SPREADSHEET_SEED_ORIGINS),
];
