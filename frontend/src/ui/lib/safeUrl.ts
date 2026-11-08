/** Protocols a link may use. */
const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:", "sms:", "tel:"]);

/** The address any other link becomes. */
export const BLOCKED_URL = "about:blank";

/** A scheme prefix (RFC 3986). */
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/** A relative reference: root-relative, a fragment, current-directory or query-only. */
const RELATIVE_REFERENCE_RE = /^[/#.?]/;

/** The value without ASCII whitespace and control characters. */
function stripControlChars(value: string): string {
  let result = "";
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (code > 0x20 && code !== 0x7f) {
      result += char;
    }
  }
  return result;
}

/**
 * The address a link, image or tab from content uses. A relative address, a
 * bare host (the caller adds its scheme) and an allowed protocol keep their
 * value; anything else becomes {@link BLOCKED_URL}. It reads the scheme itself
 * rather than with `URL`, so it runs in the server's embedded V8, which has none.
 */
export function sanitizeUrl(url: string): string {
  const trimmed = url.trim();

  if (trimmed === "") {
    return BLOCKED_URL;
  }

  if (RELATIVE_REFERENCE_RE.test(trimmed)) {
    return trimmed;
  }

  // Schemes are read without whitespace and control characters.
  const scheme = SCHEME_RE.exec(stripControlChars(trimmed));
  if (!scheme) {
    return trimmed;
  }
  return ALLOWED_PROTOCOLS.has(scheme[0].toLowerCase()) ? trimmed : BLOCKED_URL;
}
