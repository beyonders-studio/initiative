import { describe, expect, it } from "vitest";

import { pasteOverDefaultLinkUrl, validateUrl, withoutDefaultScheme } from "./url";

/** validateUrl accepts only addresses `sanitizeUrl` keeps. */
describe("validateUrl", () => {
  it("rejects dangerous schemes so they can never be stored", () => {
    expect(validateUrl("javascript:alert(1)")).toBe(false);
    expect(validateUrl("JAVASCRIPT:alert(1)")).toBe(false);
    expect(validateUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(validateUrl("vbscript:msgbox(1)")).toBe(false);
    // Loose, unanchored matchers historically allowed a javascript: URL when it
    // happened to contain a colon followed by a domain-like substring.
    expect(validateUrl("javascript:alert(document.domain)")).toBe(false);
  });

  it("accepts allowlisted absolute URLs", () => {
    expect(validateUrl("https://example.com")).toBe(true);
    expect(validateUrl("http://example.com/path")).toBe(true);
    expect(validateUrl("mailto:user@example.com")).toBe(true);
    expect(validateUrl("tel:+15555550123")).toBe(true);
  });

  it("accepts the insertion placeholder and heading anchors", () => {
    expect(validateUrl("https://")).toBe(true);
    expect(validateUrl("#some-heading")).toBe(true);
  });

  it("accepts www and bare-domain forms", () => {
    expect(validateUrl("www.example.com")).toBe(true);
    expect(validateUrl("example.com/path")).toBe(true);
  });
});

describe("withoutDefaultScheme", () => {
  it("drops the default when a full URL follows it", () => {
    expect(withoutDefaultScheme("https://https://example.com/a")).toBe("https://example.com/a");
    expect(withoutDefaultScheme("https://http://example.com")).toBe("http://example.com");
    expect(withoutDefaultScheme("https://HTTPS://example.com")).toBe("HTTPS://example.com");
    expect(withoutDefaultScheme("https://mailto:user@example.com")).toBe("mailto:user@example.com");
    expect(withoutDefaultScheme("https:// https://example.com")).toBe("https://example.com");
  });

  it("drops the default in front of a place in the app", () => {
    expect(withoutDefaultScheme("https:///c/1/projects")).toBe("/c/1/projects");
    expect(withoutDefaultScheme("https://#heading")).toBe("#heading");
  });

  it("keeps the default in front of a bare host", () => {
    expect(withoutDefaultScheme("https://")).toBe("https://");
    expect(withoutDefaultScheme("https://example.com")).toBe("https://example.com");
    expect(withoutDefaultScheme("https://localhost:3000")).toBe("https://localhost:3000");
  });

  it("leaves a URL that does not start with the default alone", () => {
    expect(withoutDefaultScheme("example.com")).toBe("example.com");
    expect(withoutDefaultScheme("http://https://example.com")).toBe("http://https://example.com");
  });

  it("leaves a URL carried later in the address alone", () => {
    expect(withoutDefaultScheme("https://example.com/?next=https://other.test")).toBe(
      "https://example.com/?next=https://other.test"
    );
  });
});

describe("pasteOverDefaultLinkUrl", () => {
  it("takes a pasted URL whole", () => {
    expect(pasteOverDefaultLinkUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(pasteOverDefaultLinkUrl("  http://example.com\n")).toBe("http://example.com");
  });

  it("keeps https:// in front of a pasted bare host", () => {
    expect(pasteOverDefaultLinkUrl("example.com/a")).toBe("https://example.com/a");
  });
});
