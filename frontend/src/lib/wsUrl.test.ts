import { describe, expect, it } from "vitest";

import { buildApiWsUrl, buildCommunityWsUrl } from "@/lib/wsUrl";

describe("WebSocket URLs", () => {
  it("addresses a community's socket under /c/, where the API serves it, in ws to an http page", () => {
    const url = new URL(buildCommunityWsUrl(4, "files/11/collaborate"));
    expect(url.pathname).toBe("/api/v1/c/4/files/11/collaborate");
    expect(new URL(buildApiWsUrl("notifications/stream")).protocol).toBe("ws:");
  });
});
