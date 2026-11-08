/**
 * Help's state, kept outside React so every Help button opens the one panel
 * the root draws, and a draft outlives the panel closing. The panel itself is
 * loaded on first open (`HelpHost`); this module is what the buttons import.
 */

import { useSyncExternalStore } from "react";

import type { SupportTopic } from "@/api/generated/initiativeAPI.schemas";

export type HelpView = "search" | "ask" | "sent";

export interface HelpDraft {
  text: string;
  topic: SupportTopic | "";
  files: File[];
  sendContext: boolean;
}

export interface HelpState {
  open: boolean;
  view: HelpView;
  query: string;
  draft: HelpDraft;
  /** The community a surface asked about; otherwise the one in the address. */
  communityId?: number | null;
}

export const EMPTY_DRAFT: HelpDraft = { text: "", topic: "", files: [], sendContext: true };

let state: HelpState = { open: false, view: "search", query: "", draft: EMPTY_DRAFT };
const listeners = new Set<() => void>();

export const updateHelp = (patch: Partial<HelpState>) => {
  state = { ...state, ...patch };
  for (const listener of listeners) listener();
};

export const setHelpDraft = (patch: Partial<HelpDraft>) =>
  updateHelp({ draft: { ...state.draft, ...patch } });

/** Help as it stands, read where an event handler needs it rather than a render. */
export const currentHelp = () => state;

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const hasDraft = (draft: HelpDraft) => draft.text.trim() !== "" || draft.files.length > 0;

/**
 * Open Help: where a draft is waiting, on it; otherwise on the search. A
 * surface that knows what the reader needs opens it on asking the team about
 * that, in that community.
 */
export const openHelp = (ask?: { topic: SupportTopic; communityId: number | null }) => {
  if (ask) {
    updateHelp({
      open: true,
      view: "ask",
      communityId: ask.communityId,
      draft: { ...state.draft, topic: ask.topic },
    });
    return;
  }
  updateHelp({ open: true, view: hasDraft(state.draft) ? "ask" : "search" });
};

/** The question mark's own action: open Help, or close it when it is open. */
export const toggleHelp = () => (state.open ? updateHelp({ open: false }) : openHelp());

export const useHelpState = () =>
  useSyncExternalStore(
    subscribe,
    () => state,
    () => state
  );

/** Whether Help is open, for the buttons that open it. */
export const useHelpOpen = () =>
  useSyncExternalStore(
    subscribe,
    () => state.open,
    () => false
  );
