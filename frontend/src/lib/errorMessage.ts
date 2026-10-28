import type { AxiosError } from "axios";
import { isAxiosError } from "axios";

import i18n from "@/i18n";
import { listFormat } from "@/lib/intl";
import { kindNames } from "@/lib/tools";

/** Loose translation function that accepts dynamic keys without strict type checking. */
const translate = i18n.t.bind(i18n) as (key: string, options?: Record<string, unknown>) => string;

/** One entry of FastAPI's 422 body: `{"detail": [{type, loc, msg}, ...]}`. */
interface ValidationDetail {
  msg?: string;
  loc?: (string | number)[];
}

/** The values a refusal's wording is filled in with, as the API sent them. */
type ErrorParams = Record<string, string>;

/** The fields a refusal names, one a line: a built-in field by its id, in the
 *  reader's words, and a property by its own name. */
const fieldList = (fields: string): string =>
  listFormat(i18n.language).format(
    fields
      .split("\n")
      .map((field) => translate(`requiredFields.${field}`, { ns: "errors", defaultValue: field }))
  );

/**
 * What a refusal's `params` fill its wording with. A `kind` names the thing
 * refused — "Project not found" — in the forms `kindNames` gives; `fields`
 * names the fields it lacks.
 */
function interpolation(params: ErrorParams | undefined): Record<string, string> {
  if (!params) return {};
  return {
    ...params,
    ...(params.kind ? kindNames(params.kind, translate) : {}),
    ...(params.fields ? { fields: fieldList(params.fields) } : {}),
  };
}

/**
 * The flat error code inside a pydantic validation message, if there is one.
 *
 * A validator that raises `ValueError("SOME_CODE")` reaches the client as
 * `"Value error, SOME_CODE"`. Everything else — a length or type failure —
 * has no code to pull out, so this returns null and the caller falls back.
 */
function codeFromValidationDetail(detail: ValidationDetail[]): string | null {
  for (const entry of detail) {
    const match = /^Value error,\s*([A-Z][A-Z0-9_]*)$/.exec(entry?.msg?.trim() ?? "");
    if (match) return match[1];
  }
  return null;
}

/**
 * Extract a user-facing error message from an API error response.
 *
 * Tries to map a backend error code (from `detail`) to a localized string
 * in the `errors` namespace. A 422 carries a list of field errors instead;
 * a flat code raised by a validator is localized the same way. Falls back to
 * the provided fallback key or the raw detail string.
 */
export function getErrorMessage(error: unknown, fallbackKey?: string): string {
  const axiosError = error as AxiosError<{
    detail?: string | ValidationDetail[];
    params?: ErrorParams;
  }>;

  const detail = axiosError?.response?.data?.detail;
  const params = axiosError?.response?.data?.params;

  // slowapi returns 429 with {"error": "..."} instead of {"detail": "..."}, so a
  // 429 with nothing in `detail` is the rate limiter and says so. The app's own
  // refusals use the same status for "not right now" — a community with no free
  // query slot — and those carry a code worth reading, so they are localized
  // like any other.
  if (axiosError?.response?.status === 429 && typeof detail !== "string") {
    return translate("RATE_LIMITED", { ns: "errors" });
  }

  // A 422 carries a list of field errors rather than a code. Localize the flat
  // code a validator raised; otherwise fall through to the caller's fallback,
  // since pydantic's own wording is not written for an end user.
  if (Array.isArray(detail)) {
    const code = codeFromValidationDetail(detail);
    if (code) {
      const localized = translate(code, { ns: "errors", defaultValue: "" });
      if (localized) return localized;
    }
    return fallbackKey ? translate(fallbackKey) : translate("fallback", { ns: "errors" });
  }

  if (detail) {
    // Try to look up the detail as a key in the errors namespace
    const localized = translate(detail, {
      ns: "errors",
      defaultValue: "",
      ...interpolation(params),
    });
    if (localized) {
      return localized;
    }
    // If it's not a known error code, return the raw detail string
    return detail;
  }

  if (fallbackKey) {
    return translate(fallbackKey);
  }

  return translate("fallback", { ns: "errors" });
}

/**
 * The backend error code carried in `detail`, if the error has one.
 *
 * For the callers that have to branch on *which* failure it was rather than
 * just show it — the codes (`app/core/messages.py`) are the machine-readable
 * half of the same contract `getErrorMessage` localizes.
 */
export function getErrorCode(error: unknown): string | null {
  if (!isAxiosError(error)) {
    return null;
  }
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  if (Array.isArray(detail)) {
    return codeFromValidationDetail(detail as ValidationDetail[]);
  }
  return typeof detail === "string" ? detail : null;
}

/**
 * The localized message for a backend code that did not arrive as an error.
 *
 * Some endpoints answer 200 and report the outcome in the body — a reachability
 * check says whether it reached rather than failing. The code means the same
 * thing either way, so it is looked up the same way.
 */
export function messageForCode(code: string | null | undefined, fallbackKey: string): string {
  if (code) {
    const translated = translate(`errors:${code}`);
    if (translated !== `errors:${code}`) return translated;
  }
  return translate(fallbackKey);
}

/**
 * Extract the HTTP status code from an error, if available.
 */
export function getHttpStatus(error: unknown): number | null {
  if (isAxiosError(error)) {
    return error.response?.status ?? null;
  }
  return null;
}
