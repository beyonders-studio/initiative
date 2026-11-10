import { type ComponentType, createElement, type ReactNode, useSyncExternalStore } from "react";

import type {
  RecurrencePreview,
  RecurrencePreviewRequest,
} from "@/api/generated/initiativeAPI.schemas";
import { BLOCKED_URL, sanitizeUrl } from "@/ui/lib/safeUrl";
import type { Member } from "@/ui/member-picker";
import type { UserValue } from "@/ui/properties/propertyHelpers";

/**
 * What the app hands the kit.
 *
 * The kit fetches nothing and knows nothing of the app around it, so what it
 * needs from that app arrives here. The reader's clock and week start change
 * while the app runs: the app writes them and components subscribe. The rest
 * is set once, at boot, with `setHost`: how to show a notice, take a picture,
 * link to a page, hold a move away from one, open another site, keep a
 * preference, find the emoji data, load the spelling dictionary, recognise the
 * app's own origin, draw a person a field names and preview a repeat's dates.
 */

export type TimeFormatPreference = "system" | "12" | "24";
export type WeekStart = 0 | 1 | 2 | 3 | 4 | 5 | 6;

export const TIME_FORMAT_PREFERENCES: readonly TimeFormatPreference[] = ["system", "12", "24"];

/** Narrow a stored or API value to a clock we know. */
export const parseTimeFormat = (value: unknown): TimeFormatPreference =>
  TIME_FORMAT_PREFERENCES.includes(value as TimeFormatPreference)
    ? (value as TimeFormatPreference)
    : "system";

/** Narrow a stored or API value to a day of the week, Sunday when it is none. */
export const parseWeekStart = (value: unknown): WeekStart =>
  Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 6
    ? (value as WeekStart)
    : 0;

/** Where a picture comes from: the camera, or the pictures already on the device. */
export type PhotoSource = "camera" | "library";

/** Why a capture produced no file. A cancelled one is not an error — it is `null`. */
export type PhotoCaptureFailure = "permission" | "unavailable" | "failed";

export class PhotoCaptureError extends Error {
  constructor(readonly reason: PhotoCaptureFailure) {
    super(`Photo capture failed: ${reason}`);
    this.name = "PhotoCaptureError";
  }
}

export interface HostLinkProps {
  to: string;
  search?: Record<string, unknown>;
  className?: string;
  /** What the link is called where its text alone does not say. */
  "aria-label"?: string;
  /** False where the link sits on something dragged, which carries the drag. */
  draggable?: boolean;
  children?: ReactNode;
}

/** A move to another of the app's pages, held while the page asks whether to
 *  leave: `proceed` lets it go on, and `reset` stays. */
export interface Blocker {
  blocked: boolean;
  proceed: () => void;
  reset: () => void;
}

const NOT_BLOCKED: Blocker = { blocked: false, proceed: () => {}, reset: () => {} };

export interface Host {
  /** Shows a short notice. */
  toast: { success: (message: string) => void; error: (message: string) => void };
  /** Takes or chooses a picture with the device, where the app can; null where
   *  the browser's file field is the only way. Fails with `PhotoCaptureError`. */
  camera: { capture: (source: PhotoSource) => Promise<File | null> } | null;
  /** A link to one of the app's own pages. */
  Link: ComponentType<HostLinkProps>;
  /** Holds a move to another of the app's pages while `when` says, and asks
   *  the browser's own question before the tab closes then. A hook. */
  useBlocker: (when: () => boolean) => Blocker;
  /** Opens another site, away from the app. */
  openExternal: (url: string) => void;
  /** Where a preference is kept between visits. */
  storage: {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
  };
  /** Where the emoji picker reads its data; the picker's own source when unset. */
  emojibaseUrl?: string;
  /** The English dictionary the editor suggests spellings from, as Hunspell's
   *  `.aff` and `.dic` texts; the editor suggests none when unset. */
  spellCheckDictionary?: () => Promise<{ aff: string; dic: string }>;
  /** Whether an address is served from the app's own origin. */
  isOwnOrigin: (url: string) => boolean;
  /** How a person a field's value names is drawn: their name, picture and
   *  initials, from the person as the server reads them back. */
  member: (person: UserValue) => Member;
  /** The next starts of a repeat, from the engine the app's calendar uses;
   *  the editor shows none when unset. */
  previewRecurrence?: (request: RecurrencePreviewRequest) => Promise<RecurrencePreview>;
}

const kept = new Map<string, string>();

export const host: Host = {
  toast: { success: () => {}, error: () => {} },
  camera: null,
  Link: ({ to, className, "aria-label": label, draggable, children }) =>
    createElement("a", { href: to, className, "aria-label": label, draggable }, children),
  useBlocker: () => NOT_BLOCKED,
  openExternal: (url) => {
    const safe = sanitizeUrl(url);
    if (safe !== BLOCKED_URL) window.open(safe, "_blank", "noopener,noreferrer");
  },
  storage: {
    getItem: (key) => kept.get(key) ?? null,
    setItem: (key, value) => kept.set(key, value),
  },
  isOwnOrigin: (url) => {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch {
      return false;
    }
  },
  member: ({ id }) => ({ id, name: `#${id}`, initials: "?" }),
};

/** Hand the kit what it needs from the app. Called at boot, before rendering. */
export const setHost = (parts: Partial<Host>): void => {
  Object.assign(host, parts);
};

/**
 * The reader's clock: whether times read "1:30 PM" or "13:30", and the day a
 * week starts on.
 *
 * Formatters deep in render trees read it as a plain value, so it lives here
 * rather than in a context. The time format is kept between visits, so a
 * returning reader's first paint is already on their clock; the app overwrites
 * both as soon as it knows the reader.
 */
export interface Clock {
  timeFormat: TimeFormatPreference;
  weekStart: WeekStart;
}

const TIME_FORMAT_KEY = "initiative.timeFormat";

// `null` until something asks: the app sets where preferences are kept at boot,
// after this module is imported.
let clock: Clock | null = null;
const listeners = new Set<() => void>();

export const getClock = (): Clock => {
  clock ??= { timeFormat: parseTimeFormat(host.storage.getItem(TIME_FORMAT_KEY)), weekStart: 0 };
  return clock;
};

/**
 * Write the reader's clock without telling anybody, and say whether it changed.
 *
 * Split from `notifyClock` so the app can write it while its root renders,
 * which puts every time below the root on the right clock in the same pass, and
 * tell subscribers after the commit.
 */
export const writeClock = (next: Partial<Clock>): boolean => {
  const current = getClock();
  const timeFormat = next.timeFormat ?? current.timeFormat;
  const weekStart = next.weekStart ?? current.weekStart;
  if (timeFormat === current.timeFormat && weekStart === current.weekStart) return false;
  clock = { timeFormat, weekStart };
  if (timeFormat !== current.timeFormat) {
    try {
      host.storage.setItem(TIME_FORMAT_KEY, timeFormat);
    } catch {
      // A browser that refuses storage still gets the right clock this session.
    }
  }
  return true;
};

export const notifyClock = (): void => {
  for (const listener of listeners) listener();
};

export const setClock = (next: Partial<Clock>): void => {
  if (writeClock(next)) notifyClock();
};

export const subscribeClock = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

const getTimeFormat = () => getClock().timeFormat;
const getWeekStart = () => getClock().weekStart;

/** The reader's time format, re-rendering the caller when it changes. A
 *  component that formats inline needs nothing: the formatters read the same
 *  value, already current by the time anything below the root renders. */
export const useTimeFormat = (): TimeFormatPreference =>
  useSyncExternalStore(subscribeClock, getTimeFormat, getTimeFormat);

/** The day the reader's week starts on, re-rendering the caller when it changes. */
export const useWeekStart = (): WeekStart =>
  useSyncExternalStore(subscribeClock, getWeekStart, getWeekStart);
