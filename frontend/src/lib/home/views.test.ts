import { describe, expect, it } from "vitest";

import {
  addView,
  canAddView,
  type HomeViews,
  initialHomeViews,
  MAX_HOME_VIEWS,
  MAX_VIEW_NAME_LENGTH,
  moveView,
  newViewId,
  readHomeViews,
  removeView,
  renameView,
} from "./views";

const three: HomeViews = {
  version: 1,
  views: [
    { id: "main", name: "Work" },
    { id: "league", name: "League" },
    { id: "allotment", name: "Allotment" },
  ],
  current: "league",
};

describe("readHomeViews", () => {
  it("has nothing worth keeping in a value that is not a list of views", () => {
    expect(readHomeViews(null)).toBeNull();
    expect(readHomeViews({ views: [] })).toBeNull();
    expect(readHomeViews({ views: [{ id: "BAD ID", name: "x" }] })).toBeNull();
  });

  it("keeps each well-formed view once, with a name a tab has room for", () => {
    const read = readHomeViews({
      views: [
        { id: "main", name: "  Work  " },
        { id: "main", name: "Again" },
        { id: "nameless", name: "   " },
        { id: "long", name: "x".repeat(100) },
        "garbage",
      ],
      current: "gone",
    });
    expect(read?.views).toEqual([
      { id: "main", name: "Work" },
      { id: "long", name: "x".repeat(MAX_VIEW_NAME_LENGTH) },
    ]);
    // A current view that is no longer there is forgotten.
    expect(read?.current).toBeUndefined();
  });
});

describe("addView", () => {
  it("goes beside the view it was made from, and is opened", () => {
    const next = addView(three, { id: "fete", name: "Fete" }, "main");
    expect(next.views.map((view) => view.id)).toEqual(["main", "fete", "league", "allotment"]);
    expect(next.current).toBe("fete");
  });

  it("stops at the most a reader may keep", () => {
    let views = initialHomeViews("Home");
    while (canAddView(views)) {
      views = addView(views, { id: newViewId(views), name: "More" });
    }
    expect(views.views).toHaveLength(MAX_HOME_VIEWS);
    expect(addView(views, { id: "onemore", name: "One more" })).toBe(views);
  });
});

describe("removeView", () => {
  it("shows the next view along in place of the one removed", () => {
    const { views, next } = removeView(three, "league");
    expect(views.views.map((view) => view.id)).toEqual(["main", "allotment"]);
    expect(next).toBe("allotment");
    expect(views.current).toBe("allotment");
  });

  it("falls back to the one before when the last is removed", () => {
    expect(removeView(three, "allotment").next).toBe("league");
  });

  it("keeps the only view there is", () => {
    const one = initialHomeViews("Home");
    expect(removeView(one, "main").views).toBe(one);
  });
});

describe("moveView and renameView", () => {
  it("moves a view one tab along, and no further than the ends", () => {
    expect(moveView(three, "league", -1).views.map((view) => view.id)).toEqual([
      "league",
      "main",
      "allotment",
    ]);
    expect(moveView(three, "main", -1)).toBe(three);
  });

  it("renames, but never to nothing", () => {
    expect(renameView(three, "main", " Day job ").views[0].name).toBe("Day job");
    expect(renameView(three, "main", "  ")).toBe(three);
  });
});
