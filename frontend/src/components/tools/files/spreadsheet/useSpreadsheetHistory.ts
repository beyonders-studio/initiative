import type * as Y from "yjs";

import { useYjsHistory, type YjsHistory } from "@/hooks/useYjsHistory";

import { UNDOABLE_SPREADSHEET_ORIGINS } from "./origins";
import { Y_SHEETS_KEY } from "./workbookDoc";

/**
 * Per-session undo/redo for the spreadsheet — a thin adapter over the
 * generic {@link useYjsHistory} primitive. The data hooks
 * (`useSpreadsheetCells` / `useSpreadsheetFormatting`) already funnel
 * every mutation through `doc.transact(fn, origin)`; this tells the
 * shared `Y.UndoManager` which shared types to watch, and takes which
 * origins are undoable from the one registry that defines them.
 */

// Everything a spreadsheet owns hangs off the single `sheets` map (see
// `workbookDoc.ts`), and a `Y.UndoManager` tracks any type whose parent
// chain reaches a scoped one — so one entry covers every sheet's cells and
// formatting, including sheets created after the manager was built.
const spreadsheetScope = (doc: Y.Doc) => [doc.getMap(Y_SHEETS_KEY)];

export const useSpreadsheetHistory = (doc: Y.Doc | null): YjsHistory =>
  useYjsHistory({
    doc,
    getScope: spreadsheetScope,
    trackedOrigins: UNDOABLE_SPREADSHEET_ORIGINS,
  });
