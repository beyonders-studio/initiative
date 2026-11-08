import type { ProviderAwareness } from "@lexical/yjs";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SheetId } from "@/lib/spreadsheet/sheets";
import { getUserColorHsl } from "@/ui/lib/userColor";

/**
 * Selection-presence awareness for the spreadsheet editor.
 *
 * Each connected client publishes ``spreadsheet_user`` (id + name) and
 * ``spreadsheet_selection`` (sheet + row + col + color + updatedAt) to
 * the shared awareness layer. Peers subscribe to render colored rings
 * and a name label on the cells other users have selected.
 *
 * The selection carries the sheet it was made on, because a workbook's
 * peers are rarely all looking at the same one — without it, a peer
 * editing Sheet2!B4 would paint a ring on Sheet1's B4.
 *
 * Same shape vocabulary the whiteboard cursor hook uses, just keyed
 * with a ``spreadsheet_*`` prefix so the two editors never collide on
 * the awareness state for a multi-doc-type session.
 */

interface SpreadsheetAwarenessUser {
  id: number;
  name: string;
}

interface SpreadsheetAwarenessSelection {
  /** The sheet the peer made this selection on. Absent from a client
   *  that predates multi-sheet; treated as "wherever you're looking". */
  sheetId?: SheetId;
  row: number;
  col: number;
  color: string;
  updatedAt: number;
}

export interface SpreadsheetPeer {
  clientId: number;
  user: SpreadsheetAwarenessUser;
  selection: SpreadsheetAwarenessSelection;
}

interface UseSpreadsheetAwarenessArgs {
  awareness: ProviderAwareness | null;
  clientId: number | null;
  user: { id: number; name: string } | null;
  selected: { row: number; col: number };
  /** The sheet on screen: scopes both what is published and which peer
   *  selections are rendered. */
  sheetId: SheetId | null;
  /** Master switch: when false, the hook neither publishes nor
   *  subscribes (collab disabled or provider not yet ready). */
  enabled: boolean;
  /** When false, the hook still subscribes to peers' selections (so
   *  e.g. read-only viewers see other users' rings) but does not
   *  publish the local user's own selection. */
  publishLocal: boolean;
}

interface UseSpreadsheetAwarenessResult {
  /** Map keyed by ``"r:c"`` for O(1) lookup during cell rendering. */
  peerSelectionsByCell: Map<string, SpreadsheetPeer>;
}

const SELECTION_KEY = "spreadsheet_selection";
const USER_KEY = "spreadsheet_user";

const PEER_TIMEOUT_MS = 30_000;

export const useSpreadsheetAwareness = ({
  awareness,
  clientId,
  user,
  selected,
  sheetId,
  enabled,
  publishLocal,
}: UseSpreadsheetAwarenessArgs): UseSpreadsheetAwarenessResult => {
  const [peers, setPeers] = useState<SpreadsheetPeer[]>([]);
  const canPublish = enabled && publishLocal;

  // Publish the local selection. Read-only viewers skip the publish
  // path (``canPublish === false``) but still subscribe below — they
  // see peer rings, just don't broadcast their own. Throttled to once
  // per requestAnimationFrame would be overkill: selection changes are
  // rare (clicks / arrow keys) so a plain effect suffices.
  const lastPublishedRef = useRef<{ sheetId: SheetId | null; row: number; col: number } | null>(
    null
  );
  useEffect(() => {
    if (!canPublish || !awareness || !user) return;
    awareness.setLocalStateField(USER_KEY, { id: user.id, name: user.name });
  }, [canPublish, awareness, user]);

  useEffect(() => {
    if (!canPublish || !awareness || !user) return;
    const last = lastPublishedRef.current;
    if (
      last &&
      last.sheetId === sheetId &&
      last.row === selected.row &&
      last.col === selected.col
    ) {
      return;
    }
    lastPublishedRef.current = { sheetId, row: selected.row, col: selected.col };
    awareness.setLocalStateField(SELECTION_KEY, {
      sheetId: sheetId ?? undefined,
      row: selected.row,
      col: selected.col,
      color: getUserColorHsl(user.id),
      updatedAt: Date.now(),
    });
  }, [canPublish, awareness, user, sheetId, selected.row, selected.col]);

  // Clear selection on unmount / when publish toggles off so peers
  // don't see a ghost cursor.
  useEffect(() => {
    if (!canPublish || !awareness) return;
    return () => {
      awareness.setLocalStateField(SELECTION_KEY, null);
    };
  }, [canPublish, awareness]);

  // Subscribe to peer state.
  useEffect(() => {
    if (!enabled || !awareness) {
      setPeers([]);
      return;
    }
    const rebuild = () => {
      const states = awareness.getStates();
      const now = Date.now();
      const next: SpreadsheetPeer[] = [];
      states.forEach((state, peerClientId) => {
        if (clientId !== null && peerClientId === clientId) return;
        const peerUser = (state as Record<string, unknown>)[USER_KEY] as
          | SpreadsheetAwarenessUser
          | undefined;
        const selection = (state as Record<string, unknown>)[SELECTION_KEY] as
          | SpreadsheetAwarenessSelection
          | undefined;
        if (!peerUser || !selection) return;
        if (now - selection.updatedAt > PEER_TIMEOUT_MS) return;
        next.push({ clientId: peerClientId, user: peerUser, selection });
      });
      setPeers(next);
    };
    rebuild();
    awareness.on("update", rebuild);
    return () => awareness.off("update", rebuild);
  }, [enabled, awareness, clientId]);

  const peerSelectionsByCell = useMemo(() => {
    // When two or more peers have the same cell selected, pick the
    // most-recently-updated one so the overlay is deterministic
    // instead of "last-seen-by-Map.set wins". v1 only renders one
    // ring per cell; if multi-peer overlap becomes common we'd swap
    // this for a stacked-rings UI, but losing one indicator silently
    // is the bug to avoid right now.
    const m = new Map<string, SpreadsheetPeer>();
    for (const peer of peers) {
      // Only peers on this sheet. A selection with no sheet came from a
      // pre-multi-sheet client, which only ever had one.
      if (peer.selection.sheetId !== undefined && peer.selection.sheetId !== sheetId) continue;
      const key = `${peer.selection.row}:${peer.selection.col}`;
      const existing = m.get(key);
      if (!existing || peer.selection.updatedAt > existing.selection.updatedAt) {
        m.set(key, peer);
      }
    }
    return m;
  }, [peers, sheetId]);

  return { peerSelectionsByCell };
};
