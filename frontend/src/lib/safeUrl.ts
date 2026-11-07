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
 * value; anything else, and anything unreadable, becomes {@link BLOCKED_URL}.
 */
export function sanitizeUrl(url: string): string {
  const trimmed = url.trim();

  if (trimmed === "") {
    return BLOCKED_URL;
  }

  // The editor's new-link placeholder keeps its value.
  if (trimmed === "https://") {
    return trimmed;
  }

  if (RELATIVE_REFERENCE_RE.test(trimmed)) {
    return trimmed;
  }

  // Schemes are read without whitespace and control characters.
  const stripped = stripControlChars(trimmed);
  if (!SCHEME_RE.test(stripped)) {
    return trimmed;
  }

  try {
    return ALLOWED_PROTOCOLS.has(new URL(stripped).protocol) ? trimmed : BLOCKED_URL;
  } catch {
    return BLOCKED_URL;
  }
}
