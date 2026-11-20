import { describe, expect, it, vi } from "vitest";

import { sanitizeUrl } from "./safeUrl";

describe("sanitizeUrl", () => {
  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    // Leading/trailing whitespace is ignored when matching the scheme.
    "  javascript:alert(1)  ",
    // Tab/newline inside the scheme name.
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "blob:https://evil.test/uuid",
    "",
    "   ",
  ])("neutralizes %j to about:blank", (url) => {
    expect(sanitizeUrl(url)).toBe("about:blank");
  });

  it.each([
    "https://example.com/path?q=1#frag",
    "http://example.com",
    "mailto:user@example.com",
    "tel:+15555550123",
    "sms:+15555550123",
    "/projects/1",
    "#heading-anchor",
    "./relative",
    "../up",
    "?query=only",
    // A bare protocol-less domain is left for the caller to format.
    "example.com/foo",
    // The floating link editor initialises/resets its URL to this placeholder,
    // so sanitizing it to about:blank would corrupt link insertion.
    "https://",
  ])("passes %j through unchanged", (url) => {
    expect(sanitizeUrl(url)).toBe(url);
  });

  it("gives the same answers with no URL global, as in the server's editor", () => {
    vi.stubGlobal("URL", undefined);
    try {
      expect(sanitizeUrl("https://example.com")).toBe("https://example.com");
      expect(sanitizeUrl("javascript:alert(1)")).toBe("about:blank");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
