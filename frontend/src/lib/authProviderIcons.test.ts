import { describe, expect, it } from "vitest";

import { FALLBACK_PROVIDER_ICON, providerIcon } from "@/lib/authProviderIcons";

describe("provider marks", () => {
  it("has a mark of its own for the providers simple-icons carries", () => {
    const carried = ["google", "okta", "auth0", "keycloak", "authentik", "authelia", "custom"];
    for (const key of carried) {
      expect(providerIcon(key), key).not.toBe(FALLBACK_PROVIDER_ICON);
    }
  });

  it("falls back for the three it does not carry, and for anything unknown", () => {
    // simple-icons has no Entra, Zitadel or Pocket ID mark. They read as their
    // names, which is most of the job; see the note in authProviderIcons.ts.
    for (const key of ["microsoft", "zitadel", "pocket-id", "made-up", null, undefined]) {
      expect(providerIcon(key), String(key)).toBe(FALLBACK_PROVIDER_ICON);
    }
  });
});
