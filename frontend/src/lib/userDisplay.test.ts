import { describe, expect, it } from "vitest";

import {
  formatDiscriminator,
  getUserDisplayName,
  getUserHandle,
  hasDisplayName,
} from "@/lib/userDisplay";

const withHandle = { id: 7, username: "foobar", discriminator: 12 };

describe("getUserHandle", () => {
  it("writes the number as four digits", () => {
    expect(getUserHandle(withHandle)).toBe("foobar#0012");
    expect(getUserHandle({ ...withHandle, discriminator: 1234 })).toBe("foobar#1234");
    expect(getUserHandle({ ...withHandle, discriminator: 0 })).toBe("foobar#0000");
  });

  it("has nothing to write without a name part", () => {
    expect(getUserHandle({ id: 7 })).toBe("");
    expect(getUserHandle(null)).toBe("");
  });
});

describe("formatDiscriminator", () => {
  it("pads, and says nothing about a missing number", () => {
    expect(formatDiscriminator(12)).toBe("0012");
    expect(formatDiscriminator(null)).toBe("");
  });
});

describe("getUserDisplayName", () => {
  it("prefers a community name", () => {
    expect(getUserDisplayName({ ...withHandle, display_name: "Jordan Drako" })).toBe(
      "Jordan Drako"
    );
  });

  it("falls back to the handle", () => {
    // Most members set no community name, so this is the ordinary case
    // rather than an edge one.
    expect(getUserDisplayName(withHandle)).toBe("foobar#0012");
    expect(getUserDisplayName({ ...withHandle, display_name: "   " })).toBe("foobar#0012");
  });

  it("keeps rendering the handle for an account no longer in use", () => {
    // The handle is a pseudonym and a unique identifier at once — an old
    // thread stays legible only if it survives the account.
    expect(getUserDisplayName({ ...withHandle, status: "anonymized" })).toBe("foobar#0012");
    expect(getUserDisplayName({ ...withHandle, status: "deactivated" })).toBe("foobar#0012");
  });

  it("names an unresolved id by its number unless the caller has a placeholder", () => {
    expect(getUserDisplayName({ id: 42 })).toBe("User #42");
    expect(getUserDisplayName(null)).toBe("User");
    expect(getUserDisplayName({ id: 42 }, "#42")).toBe("#42");
  });
});

describe("hasDisplayName", () => {
  it("is true as soon as there is a handle", () => {
    expect(hasDisplayName(withHandle)).toBe(true);
    expect(hasDisplayName({ id: 7 })).toBe(false);
  });
});
