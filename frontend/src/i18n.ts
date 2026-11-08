import type { LanguageDetectorModule } from "i18next";
import i18n from "i18next";
import HttpBackend from "i18next-http-backend";
import { initReactI18next } from "react-i18next";

import { getItem, setItem } from "@/lib/storage";

/**
 * Custom language detector that uses the app's storage abstraction
 * instead of accessing localStorage directly. This ensures language
 * preference persists correctly on native platforms via Capacitor
 * Preferences.
 */
const storageLanguageDetector: LanguageDetectorModule = {
  type: "languageDetector",
  init() {},
  detect() {
    const stored = getItem("initiative-language");
    if (stored) {
      return stored;
    }
    if (typeof navigator !== "undefined") {
      return navigator.language;
    }
    return undefined;
  },
  cacheUserLanguage(lng: string) {
    setItem("initiative-language", lng);
  },
};

void i18n
  .use(HttpBackend)
  .use(storageLanguageDetector)
  .use(initReactI18next)
  .init({
    load: "languageOnly",
    fallbackLng: "en",
    supportedLngs: ["en", "es", "fr", "de"],
    nonExplicitSupportedLngs: true,
    defaultNS: "common",
    fallbackNS: "common",
    // ``errors`` is preloaded alongside ``common`` because
    // ``getErrorMessage`` (in ``@/lib/errorMessage``) is invoked from
    // toast call sites in components whose own ``useTranslation`` may
    // not list ``errors``. Without this, a lookup on a backend code
    // like ``USER_INVALID_PASSWORD`` falls back to the raw key string
    // because the namespace bundle hasn't been fetched yet. ``ui`` is
    // preloaded because the UI kit's skeletons are Suspense fallbacks, which
    // must render without waiting on a namespace of their own.
    ns: ["common", "errors", "ui"],
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false,
    },
    backend: {
      loadPath: "/locales/{{lng}}/{{ns}}.json",
      queryStringParams: { v: __APP_VERSION__ },
    },
    react: {
      useSuspense: true,
    },
  });

export default i18n;
