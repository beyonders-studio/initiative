/**
 * Asking a phone user to rate the app in its store.
 *
 * The ask is the store's own prompt (the App Store's, Google Play's in-app
 * review) and nothing of ours comes before or after it: both stores refuse an
 * app that asks a question first, draws its own prompt, puts the store's prompt
 * behind a button, or offers anything for a rating. The store decides whether
 * its prompt shows and never says whether it did or whether a review was left,
 * so this keeps only when this install asked.
 *
 * It asks right after something the person finished (a task done, an item
 * made), once the app has been used on {@link DAYS_BEFORE_ASKING} days, then no
 * sooner than {@link DAYS_BETWEEN_ASKS} days later and no more than
 * {@link ASKS_PER_YEAR} times a year. Only an app a store installed asks: iOS,
 * and an Android app from Google Play. An APK, the dev app, the desktop app and
 * the web never do.
 */

import { Capacitor } from "@capacitor/core";
import { useEffect, useState } from "react";

import { PLAY_STORE_URL } from "@/lib/links";
import { PLAY_STORE_INSTALLER } from "@/lib/playStore";
import { getItem, setItem } from "@/lib/storage";

// Loaded when first asked rather than at import, as `storeSelling` does.
const appEnvironment = () => import("@/plugins/appEnvironment").then((m) => m.default);

const KEY = "initiative-store-review";
const DAY_MS = 24 * 60 * 60 * 1000;

/** Days the app has been opened on before it first asks. */
export const DAYS_BEFORE_ASKING = 3;
/** The shortest wait between two asks. */
export const DAYS_BETWEEN_ASKS = 120;
/** The most asks in any 365 days, the App Store's own limit. */
export const ASKS_PER_YEAR = 3;
/** How long after the success the prompt comes, so its own feedback lands first. */
const ASK_DELAY_MS = 1500;

export interface ReviewRecord {
  /** Distinct days the app was used on, counted up to {@link DAYS_BEFORE_ASKING}. */
  days: number;
  /** The last of them, as the device's local `YYYY-MM-DD`. */
  lastDay: string | null;
  /** When this install asked, in epoch milliseconds, newest last. */
  asked: number[];
}

const EMPTY: ReviewRecord = { days: 0, lastDay: null, asked: [] };

const read = (): ReviewRecord => {
  try {
    const parsed = JSON.parse(getItem(KEY) ?? "null") as Partial<ReviewRecord> | null;
    if (!parsed) return EMPTY;
    return {
      days: typeof parsed.days === "number" ? parsed.days : 0,
      lastDay: typeof parsed.lastDay === "string" ? parsed.lastDay : null,
      asked: Array.isArray(parsed.asked)
        ? parsed.asked.filter((at): at is number => typeof at === "number")
        : [],
    };
  } catch {
    return EMPTY;
  }
};

const write = (record: ReviewRecord) => void setItem(KEY, JSON.stringify(record));

const localDay = (now: Date): string =>
  `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

const isStorePlatform = (): boolean => {
  const platform = Capacitor.getPlatform();
  return platform === "ios" || platform === "android";
};

/** Counts today as a day of use, once. */
export const noteDayOfUse = (now = new Date()): void => {
  if (!isStorePlatform()) return;
  const record = read();
  const today = localDay(now);
  if (record.lastDay === today) return;
  write({ ...record, days: Math.min(record.days + 1, DAYS_BEFORE_ASKING), lastDay: today });
};

/** Whether this install may ask now. */
export const dueForReview = (record: ReviewRecord, now: number): boolean => {
  if (record.days < DAYS_BEFORE_ASKING) return false;
  const lastYear = record.asked.filter((at) => now - at < 365 * DAY_MS);
  if (lastYear.length >= ASKS_PER_YEAR) return false;
  const last = record.asked.at(-1);
  return last === undefined || now - last >= DAYS_BETWEEN_ASKS * DAY_MS;
};

/** Whether a store installed this app, which is where a rating goes. */
const fromStore = async (): Promise<boolean> => {
  const platform = Capacitor.getPlatform();
  if (platform === "ios") return true;
  if (platform !== "android") return false;
  const { installer } = await (await appEnvironment()).get();
  return installer === PLAY_STORE_INSTALLER;
};

let asking = false;

/**
 * Called after something the person finished. Hands the store its prompt when
 * this install is due one, and otherwise does nothing.
 */
export const askForStoreReview = (): void => {
  if (asking || !isStorePlatform()) return;
  noteDayOfUse();
  if (!dueForReview(read(), Date.now())) return;
  asking = true;
  void (async () => {
    try {
      if (!(await fromStore())) return;
      await new Promise((resolve) => setTimeout(resolve, ASK_DELAY_MS));
      await (await appEnvironment()).requestReview();
      const record = read();
      write({ ...record, asked: [...record.asked, Date.now()].slice(-ASKS_PER_YEAR) });
    } catch {
      // An app built before the method, or a store that could not be reached:
      // nothing was asked, so nothing is recorded.
    } finally {
      asking = false;
    }
  })();
};

/**
 * The store page this install can be rated on, for a "Rate Initiative" row:
 * Google Play's for a Play install. The store's prompt itself is never put
 * behind a button, since the store may not show it.
 */
export const useStoreListing = (): string | null => {
  const [listing, setListing] = useState<string | null>(null);
  useEffect(() => {
    if (Capacitor.getPlatform() !== "android") return;
    let live = true;
    fromStore()
      .then((store) => {
        if (live && store) setListing(PLAY_STORE_URL);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return listing;
};

/** For tests: forget an ask in flight. */
export const resetStoreReview = (): void => {
  asking = false;
};
