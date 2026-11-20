/**
 * Every widget failure has a message, in every language we ship.
 *
 * The error tile is the only thing a viewer sees when a widget goes wrong, so
 * an unlocalized code there is a raw machine string on someone's dashboard.
 * Adding a failure mode without a translation fails here instead.
 */
import { describe, expect, it } from "vitest";

import { WidgetErrorCode } from "./errors";

const WIDGET_ERROR_CODES: string[] = Object.values(WidgetErrorCode);

const localeModules = import.meta.glob<Record<string, unknown>>(
  "../../../public/locales/*/dashboards.json",
  { eager: true, import: "default" }
);

const locales = Object.entries(localeModules).map(([path, messages]) => ({
  locale: path.split("/").at(-2) as string,
  widgetError: (messages.widgetError ?? {}) as Record<string, string>,
}));

describe("widget error messages", () => {
  // Every other locale carries exactly en's keys (`locale-keys.test.ts`).
  it("has a message for every error code and no other, in en", () => {
    const english = locales.find((entry) => entry.locale === "en")?.widgetError ?? {};
    expect(Object.keys(english).sort()).toEqual([...WIDGET_ERROR_CODES, "default"].sort());
  });

  it.each(locales)(
    "$locale has a message for every error code, translated rather than copied from en",
    ({ locale, widgetError }) => {
      const blank = [...WIDGET_ERROR_CODES, "default"].filter((key) => !widgetError[key]?.trim());
      expect(blank, `${locale} has no message for: ${blank.join(", ")}`).toHaveLength(0);
      if (locale === "en") return;
      const english = locales.find((entry) => entry.locale === "en")?.widgetError ?? {};
      const identical = Object.keys(widgetError).filter((key) => widgetError[key] === english[key]);
      expect(identical, `${locale} left untranslated: ${identical.join(", ")}`).toHaveLength(0);
    }
  );
});
