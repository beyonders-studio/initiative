import { describe, expect, it } from "vitest";

import { EMPTY_PLACE } from "@/lib/directoryNear";

import { locationOf } from "./CommunityLocationPanel";

describe("locationOf", () => {
  it("is the place as typed and pinned, with the community's own name for it", () => {
    const seattle = {
      text: " 1 Queen Anne Ave N, Seattle, Washington, United States ",
      country: "US",
      latitude: 47.6,
      longitude: -122.3,
    };

    expect(locationOf(seattle, " Queen Anne Neighborhood ")).toEqual({
      text: "1 Queen Anne Ave N, Seattle, Washington, United States",
      label: "Queen Anne Neighborhood",
      country: "US",
      latitude: 47.6,
      longitude: -122.3,
    });
    // Unpinned text is a location too; a name with no place is none.
    expect(locationOf({ ...EMPTY_PLACE, text: "The old mill" }, "")).toEqual({
      text: "The old mill",
      label: null,
      country: null,
      latitude: null,
      longitude: null,
    });
    expect(locationOf(EMPTY_PLACE, "Queen Anne Neighborhood")).toBeNull();
  });
});
