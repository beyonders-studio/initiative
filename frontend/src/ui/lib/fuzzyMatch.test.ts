import { describe, expect, it } from "vitest";

import { commandFilter } from "./fuzzyMatch";

describe("commandFilter", () => {
  it("ranks the whole name over a name it starts", () => {
    expect(commandFilter("calendar", "calendar")).toBeGreaterThan(
      commandFilter("calendar-1", "calendar")
    );
  });

  it("reads a hyphen or underscore as a space", () => {
    expect(commandFilter("arrow-right", "arrow right")).toBe(1);
    expect(commandFilter("arrow_right", "arrow-r")).toBeGreaterThanOrEqual(0.9);
  });

  it("ranks a keyword below the same match in the name", () => {
    expect(commandFilter("house", "house")).toBeGreaterThan(
      commandFilter("air-vent", "house", ["house"])
    );
  });

  it("ranks a match at the start over one inside, and either over letters in order", () => {
    const start = commandFilter("calendar", "cal");
    const inside = commandFilter("my calendar", "cal");
    const inOrder = commandFilter("calendar", "cdr");
    expect(start).toBeGreaterThan(inside);
    expect(inside).toBeGreaterThan(inOrder);
    expect(inOrder).toBeGreaterThanOrEqual(0.1);
  });

  it.each([
    ["a swapped letter", "calendar", "calnedar"],
    ["a wrong letter", "settings", "sertings"],
    ["an extra letter", "project", "projecct"],
    ["a slip in a half-typed word", "notifications", "ntoif"],
    ["the words of a name kept apart", "arrow-right", "right arrow"],
  ])("forgives %s, below every match in order", (_, text, search) => {
    const score = commandFilter(text, search);
    expect(score).toBeGreaterThan(0);
    expect(score).toBeLessThan(0.1);
  });

  it("finds a word with a letter left out as letters in order", () => {
    expect(commandFilter("dashboard", "dashbord")).toBeGreaterThanOrEqual(0.1);
  });

  it("allows one slip up to seven letters and two from eight", () => {
    expect(commandFilter("project", "porjcet")).toBe(0);
    expect(commandFilter("calendar", "claendra")).toBeGreaterThan(0);
  });

  it("forgives nothing in a word shorter than four letters", () => {
    expect(commandFilter("tag", "tga")).toBe(0);
    expect(commandFilter("calendar", "cat")).toBe(0);
  });

  it("scores fewer slips above more", () => {
    expect(commandFilter("calendar", "calnedar")).toBeGreaterThan(
      commandFilter("calendar", "claendra")
    );
  });

  it("matches on a keyword when the value does not", () => {
    expect(commandFilter("arrow-right", "nxet", ["next", "forward"])).toBeGreaterThan(0);
  });
});
