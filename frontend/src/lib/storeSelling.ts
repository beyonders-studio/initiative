/**
 * Whether this device may lead anyone to a purchase on the web.
 *
 * The web and the desktop app always may. The phone apps follow their store's
 * rules for linking out to a web checkout, which depend on the country of the
 * store account:
 *
 * - iOS: the App Store allows a link to an outside purchase on the US
 *   storefront only.
 * - Android installed from Google Play: Play allows it in the countries listed
 *   below, read from the Play billing country.
 * - Android installed any other way (an APK, Obtainium): Play's rules do not
 *   apply, so it sells as the web does. An install whose installer Android
 *   does not report is treated as a store install.
 *
 * When the store cannot say — an older native build without the method, no
 * storefront, Play billing unavailable, no answer in time — a store install
 * does not sell.
 *
 * Whether a purchase can be made at all is a separate question: a deployment
 * with no billing portal (`billing: null` from `/config`) never sells, whatever
 * this says.
 */

import { Capacitor } from "@capacitor/core";
import { useEffect, useState } from "react";

import { PLAY_STORE_INSTALLER } from "@/lib/playStore";

// Loaded when first asked rather than at import, so a module that only reads
// the answer does not register the native plugin.
const appEnvironment = () => import("@/plugins/appEnvironment").then((m) => m.default);

/**
 * Where each store lets the app link to a web purchase, as ISO 3166-1 alpha-2
 * codes.
 *
 * Google Play: the US, the UK, Australia and the EEA (EU 27 plus Iceland,
 * Liechtenstein and Norway). Japan ("JP") and South Korea ("KR") join from
 * 2026-12-31; they are not listed yet.
 */
export const SELLING_COUNTRIES = {
  ios: ["US"],
  android: [
    "US",
    "GB",
    "AU",
    // EU
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
    // EEA outside the EU
    "IS",
    "LI",
    "NO",
  ],
} as const satisfies Record<"ios" | "android", readonly string[]>;

/** Alpha-3 codes the stores may report, for every country a list above names
 *  or is expected to name. */
const ALPHA3_TO_ALPHA2: Record<string, string> = {
  USA: "US",
  GBR: "GB",
  AUS: "AU",
  AUT: "AT",
  BEL: "BE",
  BGR: "BG",
  HRV: "HR",
  CYP: "CY",
  CZE: "CZ",
  DNK: "DK",
  EST: "EE",
  FIN: "FI",
  FRA: "FR",
  DEU: "DE",
  GRC: "GR",
  HUN: "HU",
  IRL: "IE",
  ITA: "IT",
  LVA: "LV",
  LTU: "LT",
  LUX: "LU",
  MLT: "MT",
  NLD: "NL",
  POL: "PL",
  PRT: "PT",
  ROU: "RO",
  SVK: "SK",
  SVN: "SI",
  ESP: "ES",
  SWE: "SE",
  ISL: "IS",
  LIE: "LI",
  NOR: "NO",
  JPN: "JP",
  KOR: "KR",
};

/**
 * A store country as alpha-2: two letters pass through, a known alpha-3 code
 * is mapped, and anything else is unknown.
 */
export const toAlpha2 = (code: string | null | undefined): string | undefined => {
  const upper = code?.trim().toUpperCase();
  if (!upper) return undefined;
  if (/^[A-Z]{2}$/.test(upper)) return upper;
  return ALPHA3_TO_ALPHA2[upper];
};

export interface SellingFacts {
  /** `Capacitor.getPlatform()`: "web", "electron", "ios" or "android". */
  platform: string;
  /** Android only: the package that installed the app. */
  installer?: string;
  /** The store country, alpha-2 or alpha-3, when the store said. */
  country?: string;
}

/** The decision itself, from what is known about the device. */
export const sellsWith = ({ platform, installer, country }: SellingFacts): boolean => {
  if (platform === "ios" || (platform === "android" && installer === PLAY_STORE_INSTALLER)) {
    const alpha2 = toAlpha2(country);
    const allowed: readonly string[] = SELLING_COUNTRIES[platform];
    return alpha2 !== undefined && allowed.includes(alpha2);
  }
  // The web, the desktop app, and an Android app not installed from Play.
  return true;
};

/** How long to wait for the store before treating it as having no answer. */
const STORE_TIMEOUT_MS = 8000;

const withTimeout = <T>(promise: Promise<T>, fallback: T): Promise<T> =>
  new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), STORE_TIMEOUT_MS);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(fallback);
      }
    );
  });

const storeCountry = (): Promise<string | undefined> =>
  withTimeout(
    appEnvironment()
      .then((plugin) => plugin.storeCountry())
      .then((answer) => answer?.country),
    undefined
  );

const isStorePlatform = (platform: string): boolean => platform === "ios" || platform === "android";

let pending: Promise<boolean> | null = null;
let settled: boolean | undefined;
const listeners = new Set<(sells: boolean) => void>();

const decide = async (): Promise<boolean> => {
  const platform = Capacitor.getPlatform();
  if (!isStorePlatform(platform)) return true;
  if (platform === "android") {
    // No answer about the installer is not knowing it is outside Play.
    const environment = await withTimeout(
      appEnvironment().then((plugin) => plugin.get()),
      null
    );
    if (!environment) return false;
    const { installer } = environment;
    // An installer Android would not name could still be Play.
    if (!installer) return false;
    if (installer !== PLAY_STORE_INSTALLER) return true;
    return sellsWith({ platform, installer, country: await storeCountry() });
  }
  return sellsWith({ platform, country: await storeCountry() });
};

/** Asks once per app run; every later call gets the same answer. */
export const sellsOnThisDevice = (): Promise<boolean> => {
  if (!pending) {
    pending = decide()
      .catch(() => false)
      .then((sells) => {
        settled = sells;
        for (const listener of listeners) listener(sells);
        return sells;
      });
  }
  return pending;
};

/**
 * The answer if it is known without waiting: always on the web and the
 * desktop app, and on a phone once `sellsOnThisDevice` has settled.
 */
export const storeSellingNow = (): boolean | undefined => {
  if (!isStorePlatform(Capacitor.getPlatform())) return true;
  return settled;
};

/** For tests: forget the answer so the next call asks again. */
export const resetStoreSelling = (): void => {
  pending = null;
  settled = undefined;
  listeners.clear();
};

/**
 * Whether this device may sell, for a component: undefined until a phone's
 * store has answered.
 */
export const useStoreSellingAnswer = (): boolean | undefined => {
  const [sells, setSells] = useState<boolean | undefined>(storeSellingNow);
  useEffect(() => {
    const known = storeSellingNow();
    if (known !== undefined) {
      setSells(known);
      return;
    }
    listeners.add(setSells);
    void sellsOnThisDevice();
    return () => {
      listeners.delete(setSells);
    };
  }, []);
  return sells;
};
