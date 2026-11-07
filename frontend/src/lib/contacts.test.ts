import { describe, expect, it } from "vitest";

import { mailtoHref } from "./contacts";

describe("mailtoHref", () => {
  it("writes to the one address it is given", () => {
    expect(mailtoHref("ada@example.com")).toBe("mailto:ada@example.com");
    expect(mailtoHref("ada@example.com?bcc=eve@example.com")).toBe(
      "mailto:ada@example.com%3Fbcc%3Deve@example.com"
    );
  });
});
