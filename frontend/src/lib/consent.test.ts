import fs from "node:fs";
import path from "node:path";

import { beforeEach, describe, expect, it } from "vitest";

import {
  ConsentCategory,
  getConsentState,
  hasConsent,
  KNOWN_CONSENT_CATEGORIES,
  recordConsent,
  reopenConsent,
  subscribeToConsent,
} from "@/lib/consent";
import { removeItem, setItem } from "@/lib/storage";

const LOCALES_DIR = path.resolve(__dirname, "../../public/locales");

const stored = (record: unknown) => setItem("cookie-consent", JSON.stringify(record));
const answer = (granted: string[], version = 1) => ({
  version,
  decidedAt: "2026-09-20T00:00:00.000Z",
  granted,
});

describe("what a browser arrives holding", () => {
  beforeEach(() => removeItem("cookie-consent"));

  it("counts a browser that has never answered as having refused", () => {
    expect(getConsentState().record).toBeNull();
    for (const category of KNOWN_CONSENT_CATEGORIES) {
      expect(hasConsent(category)).toBe(false);
    }
  });

  it("can name and describe every category it knows, in every locale", () => {
    const locales = fs
      .readdirSync(LOCALES_DIR, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
    expect(locales.length).toBeGreaterThan(0);

    for (const locale of locales) {
      const legal = JSON.parse(
        fs.readFileSync(path.join(LOCALES_DIR, locale, "legal.json"), "utf-8")
      ) as { cookies: { categories: Record<string, { name?: string; description?: string }> } };

      for (const category of KNOWN_CONSENT_CATEGORIES) {
        const entry = legal.cookies.categories[category];
        expect(entry?.name, `${locale}: ${category} has no name`).toBeTruthy();
        expect(entry?.description, `${locale}: ${category} has no description`).toBeTruthy();
      }
    }
  });

  it("honours an answer this browser gave before", () => {
    stored(answer(["analytics"]));

    expect(hasConsent(ConsentCategory.analytics)).toBe(true);
    expect(hasConsent(ConsentCategory.marketing)).toBe(false);
  });

  it("puts the question again where the answer was to an older one, or is unreadable", () => {
    stored(answer(["analytics"], 0));

    expect(getConsentState().record).toBeNull();
    expect(hasConsent(ConsentCategory.analytics)).toBe(false);

    // Rather than guessing, where the answer is unreadable.
    setItem("cookie-consent", "{ not json");

    expect(getConsentState().record).toBeNull();
  });

  it("drops a category it no longer recognises instead of the whole answer", () => {
    stored(answer(["analytics", "something-we-retired"]));

    expect(getConsentState().record?.granted).toEqual(["analytics"]);
  });

  it("picks up an answer given somewhere else, such as another tab", () => {
    expect(hasConsent(ConsentCategory.analytics)).toBe(false);

    stored(answer(["analytics"]));

    expect(hasConsent(ConsentCategory.analytics)).toBe(true);
  });

  it("hands back the same snapshot while nothing has changed", () => {
    expect(getConsentState()).toBe(getConsentState());
  });
});

describe("answering", () => {
  beforeEach(() => removeItem("cookie-consent"));

  it("never withholds what the app cannot run without", () => {
    recordConsent([]);

    expect(hasConsent(ConsentCategory.necessary)).toBe(true);
  });

  it("does not store the essential category as though it were a choice", () => {
    recordConsent([ConsentCategory.necessary, ConsentCategory.analytics]);

    expect(getConsentState().record?.granted).toEqual([ConsentCategory.analytics]);
  });

  it("says what an answer took back, so the caller can act on it", () => {
    recordConsent(KNOWN_CONSENT_CATEGORIES);

    expect(recordConsent([ConsentCategory.analytics]).revoked).toEqual([ConsentCategory.marketing]);
    expect(recordConsent([ConsentCategory.analytics]).revoked).toEqual([]);
  });

  it("records which question was answered, and when", () => {
    recordConsent([ConsentCategory.analytics]);

    const record = getConsentState().record;
    expect(record?.version).toBe(1);
    expect(Number.isNaN(Date.parse(record?.decidedAt ?? ""))).toBe(false);
  });

  it("tells subscribers, until they stop listening", () => {
    let calls = 0;
    const unsubscribe = subscribeToConsent(() => {
      calls += 1;
    });

    recordConsent([ConsentCategory.analytics]);
    reopenConsent();
    expect(calls).toBe(2);

    unsubscribe();
    recordConsent([]);
    expect(calls).toBe(2);
  });
});
