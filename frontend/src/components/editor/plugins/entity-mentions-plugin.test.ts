import { describe, expect, it } from "vitest";

import { entityMatch } from "./entity-mentions-plugin";

describe("what a # in a document matches", () => {
  // The whole trigger is handed back to replace, so no # is left behind, and
  // the type word is kept, which is what narrowing is read from.
  it.each([
    ["see #ven", "ven", "#ven"],
    ["see #task:ven", "task:ven", "#task:ven"],
    ["see #", "", "#"],
  ])("matches %j", (text, matchingString, replaceableString) => {
    expect(entityMatch(text)).toMatchObject({ matchingString, replaceableString });
  });

  // @ is the people plugin's, and a # mid-word is not a trigger.
  it.each(["see @al", "issue#42"])("leaves %j alone", (text) => {
    expect(entityMatch(text)).toBeNull();
  });
});
