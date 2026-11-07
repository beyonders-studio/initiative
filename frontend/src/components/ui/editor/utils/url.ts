import { BLOCKED_URL, sanitizeUrl } from "@/lib/safeUrl";

/** What the link field holds before anyone has typed or pasted a URL. */
export const DEFAULT_LINK_URL = "https://";

// A destination that needs no scheme in front of it: one of its own
// (`https://…`, `mailto:…`) or a place in the app (`/…`, `#…`).
const OWN_DESTINATION_RE = /^(?:[a-z][a-z0-9+.-]*:\/\/|(?:mailto|tel|sms):|[/#])/i;

/**
 * The link field's value with the starting `https://` dropped when what
 * follows it already says where it goes, so a URL pasted after it stands
 * alone instead of reading `https://https://…`.
 */
export function withoutDefaultScheme(value: string): string {
  if (!value.toLowerCase().startsWith(DEFAULT_LINK_URL)) {
    return value;
  }
  const rest = value.slice(DEFAULT_LINK_URL.length).trimStart();
  return OWN_DESTINATION_RE.test(rest) ? rest : value;
}

/**
 * The link field's value after `pasted` lands on the untouched default: the
 * pasted URL in its place, wherever the caret was, with `https://` kept in
 * front of a bare host.
 */
export function pasteOverDefaultLinkUrl(pasted: string): string {
  return withoutDefaultScheme(DEFAULT_LINK_URL + pasted.trim());
}

// What validateUrl accepts as a whole: an absolute http, https, mailto, tel or
// sms URL, a "www."/email-prefixed host, or a bare domain with a path.
const urlRegExp = new RegExp(
  /^(?:(?:https?|mailto|tel|sms):[^\s]+|(?:www\.|[-;:&=+$,\w]+@)[A-Za-z0-9.-]+(?:\/[^\s]*)?|[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:\/[^\s]*)?)$/i
);

export function validateUrl(url: string): boolean {
  const trimmed = url.trim();

  // Allow hash-only links for heading anchors (e.g. #some-heading)
  if (trimmed.startsWith("#") && trimmed.length > 1) {
    return true;
  }

  // Only an address the allowlist keeps may become a link.
  if (sanitizeUrl(trimmed) === BLOCKED_URL) {
    return false;
  }

  // TODO Fix UI for link insertion; it should never default to an invalid URL such as https://.
  // Maybe show a dialog where the user can type the URL before inserting it.
  return trimmed === "https://" || urlRegExp.test(trimmed);
}
