/**
 * Smart chips — a chip that shows what a thing is doing right now.
 *
 * A `#` mention stores a label and is finished. A chip stores a *reference*
 * and never is: the document holds the pointer, the server holds the truth, and
 * the chip re-reads it. Moving a card changes every chip pointing at it,
 * in every document, without any of them being edited.
 *
 * What can be shown is `SmartChipKind` — generated from the server's own
 * registry, so this file cannot offer one nothing answers.
 */

import {
  SearchEntityType,
  SmartChipKind,
  type SmartChipState,
  SmartChipTone,
} from "@/api/generated/initiativeAPI.schemas";
import { CHIP_TONE_CLASSES } from "@/ui/editor/editor-ui/chip-tones";

/** How the parts of a reference are joined — mirrors `REF_SEPARATOR`. */
const SEPARATOR = ":";

/** Every chip that can be inserted, in menu order. */
export const SMART_CHIP_KINDS: SmartChipKind[] = Object.values(SmartChipKind);

/** Whether a stored string still names a chip this build offers. */
export const isSmartChipKind = (value: string): value is SmartChipKind =>
  (SMART_CHIP_KINDS as string[]).includes(value);

/** The thing a chip is about. */
export const chipEntityType = (kind: SmartChipKind): SearchEntityType =>
  kind.split(SEPARATOR)[0] as SearchEntityType;

/** The changing fact it shows. */
export const chipAspect = (kind: SmartChipKind): string => kind.split(SEPARATOR)[1];

/** Every kind of thing a chip can be about, once each. */
export const CHIP_ENTITY_TYPES: SearchEntityType[] = [
  ...new Set(SMART_CHIP_KINDS.map(chipEntityType)),
];

/** The facts offered about one kind of thing — what a picker asks after the
 *  thing itself has been chosen. */
export const chipKindsFor = (entityType: SearchEntityType): SmartChipKind[] =>
  SMART_CHIP_KINDS.filter((kind) => chipEntityType(kind) === entityType);

/** What a document stores for one chip: `task:12:status`. */
export const chipRef = (kind: SmartChipKind, entityId: number): string =>
  `${chipEntityType(kind)}${SEPARATOR}${entityId}${SEPARATOR}${chipAspect(kind)}`;

/** What a link stores: `task:12`, which resolves to what it is called now. */
export const referenceRef = (entityType: SearchEntityType, entityId: number): string =>
  `${entityType}${SEPARATOR}${entityId}`;

/** The kind a stored reference names, or `null` if it names none. */
export const storedEntityType = (value: string): SearchEntityType | null =>
  Object.hasOwn(SearchEntityType, value) ? (value as SearchEntityType) : null;

/**
 * What a chip shows, given what came back for it.
 *
 * A state that did not come back is a thing that is gone or that this reader
 * cannot open — the same answer either way — so the chip falls back to the
 * label the document stored beside it, with nothing claimed about its state.
 */
export interface ChipDisplay {
  text: string;
  className: string;
  /** Set only where the thing carries its own colour. */
  color?: string;
  /** Whether this is the live reading or the words the document stored. */
  live: boolean;
}

export const chipDisplay = (
  fallback: string,
  state: SmartChipState | undefined,
  formatDate: (iso: string) => string,
  emptyLabel: string
): ChipDisplay => {
  // Nothing came back: the thing is gone, or out of this reader's reach. The
  // label the document stored is all there is to show.
  if (!state) {
    return { text: fallback, className: CHIP_TONE_CLASSES[SmartChipTone.muted], live: false };
  }
  // An answered chip with nothing in it — an unassigned task, a date not set —
  // says so. Falling back to the stored label here would put the task's title
  // where its assignee goes.
  if (!state.text && !state.date && state.number == null) {
    return { text: emptyLabel, className: CHIP_TONE_CLASSES[state.tone], live: true };
  }
  // A date and a number belong in the reader's locale, which only the browser
  // knows; the server's `text` is what stands in until it is formatted.
  return {
    text: state.date ? formatDate(state.date) : state.text,
    className: CHIP_TONE_CLASSES[state.tone],
    color: state.color ?? undefined,
    live: true,
  };
};
