import { describe, expect, it, vi } from "vitest";

// Stub the i18n module so the policy returns its lookup key — we can
// then assert on which key was requested without booting i18next.
vi.mock("@/i18n", () => ({
  default: { t: (key: string) => key },
}));

import { checkNewPassword, PASSWORD_MIN_LENGTH } from "./passwordPolicy";

describe("checkNewPassword", () => {
  it("asks for a matching confirmation before anything else", () => {
    expect(checkNewPassword("a".repeat(PASSWORD_MIN_LENGTH), "b")).toBe(
      "auth:passwordPolicy.mismatch"
    );
    expect(checkNewPassword("short", "other")).toBe("auth:passwordPolicy.mismatch");
  });

  it("holds a matching pair to the minimum length, and to nothing else", () => {
    const short = "a".repeat(PASSWORD_MIN_LENGTH - 1);
    expect(checkNewPassword(short, short)).toBe("auth:passwordPolicy.minLength");
    const exact = "a".repeat(PASSWORD_MIN_LENGTH);
    expect(checkNewPassword(exact, exact)).toBeNull();
    // Mirror of the NIST 800-63B stance: no class requirements client-side.
    expect(checkNewPassword("all-lowercase-passphrase", "all-lowercase-passphrase")).toBeNull();
  });
});
