import { describe, expect, it } from "vitest";

import { sanitizeUrl } from "./safeUrl";

describe("sanitizeUrl", () => {
  it("neutralizes javascript: URLs to about:blank", () => {
    expect(sanitizeUrl("javascript:alert(1)")).toBe("about:blank");
    expect(sanitizeUrl("JavaScript:alert(1)")).toBe("about:blank");
    // Leading/trailing whitespace is ignored when matching the scheme.
    expect(sanitizeUrl("  javascript:alert(1)  ")).toBe("about:blank");
    // Tab/newline inside the scheme name.
    expect(sanitizeUrl("java\tscript:alert(1)")).toBe("about:blank");
  });

  it("neutralizes other dangerous schemes", () => {
    expect(sanitizeUrl("data:text/html,<script>alert(1)</script>")).toBe("about:blank");
    expect(sanitizeUrl("vbscript:msgbox(1)")).toBe("about:blank");
    expect(sanitizeUrl("file:///etc/passwd")).toBe("about:blank");
    expect(sanitizeUrl("blob:https://evil.test/uuid")).toBe("about:blank");
  });

  it("passes allowlisted absolute URLs through unchanged", () => {
    expect(sanitizeUrl("https://example.com/path?q=1#frag")).toBe(
      "https://example.com/path?q=1#frag"
    );
    expect(sanitizeUrl("http://example.com")).toBe("http://example.com");
    expect(sanitizeUrl("mailto:user@example.com")).toBe("mailto:user@example.com");
    expect(sanitizeUrl("tel:+15555550123")).toBe("tel:+15555550123");
    expect(sanitizeUrl("sms:+15555550123")).toBe("sms:+15555550123");
  });

  it("passes relative references through unchanged", () => {
    expect(sanitizeUrl("/projects/1")).toBe("/projects/1");
    expect(sanitizeUrl("#heading-anchor")).toBe("#heading-anchor");
    expect(sanitizeUrl("./relative")).toBe("./relative");
    expect(sanitizeUrl("../up")).toBe("../up");
    expect(sanitizeUrl("?query=only")).toBe("?query=only");
  });

  it("leaves bare protocol-less domains for the caller to format", () => {
    expect(sanitizeUrl("example.com/foo")).toBe("example.com/foo");
  });

  it("neutralizes empty input", () => {
    expect(sanitizeUrl("")).toBe("about:blank");
    expect(sanitizeUrl("   ")).toBe("about:blank");
  });
});

describe("sanitizeUrl link-insertion placeholder", () => {
  it("passes the https:// placeholder through unchanged", () => {
    // The floating link editor initialises/resets editedLinkUrl to "https://";
    // sanitizing it to about:blank would corrupt link insertion (PR review P1).
    expect(sanitizeUrl("https://")).toBe("https://");
  });
});
