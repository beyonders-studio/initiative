import { describe, expect, it } from "vitest";

import { routeTemplate } from "@/components/tickets/DeviceContext";

describe("routeTemplate", () => {
  it("drops the layout segments and keeps every id as its parameter", () => {
    expect(routeTemplate("/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/")).toBe(
      "/c/$communityId/i/$initiativeId"
    );
    expect(routeTemplate("/_serverRequired/_authenticated/")).toBe("/");
  });
});
