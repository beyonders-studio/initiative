import { describe, expect, it } from "vitest";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { activeMention, ENTITY_TRIGGER } from "@/lib/mentions";

import { entityMatch } from "./entity-mentions-plugin";

describe("what a # in a document matches", () => {
  it("triggers on # and leaves @ to the people plugin", () => {
    expect(entityMatch("see #ven")).not.toBeNull();
    expect(entityMatch("see @al")).toBeNull();
  });

  it("hands back the whole trigger to replace, so no # is left behind", () => {
    const match = entityMatch("see #ven");
    expect(match?.replaceableString).toBe("#ven");
  });

  it("keeps the type word, which is what narrowing is read from", () => {
    const match = entityMatch("see #task:ven");
    expect(match?.matchingString).toBe("task:ven");
    expect(match?.replaceableString).toBe(`${ENTITY_TRIGGER}task:ven`);
  });

  it("does not trigger mid-word", () => {
    expect(entityMatch("issue#42")).toBeNull();
  });

  it("offers as soon as the trigger is typed, before any letters", () => {
    expect(entityMatch("see #")?.matchingString).toBe("");
  });
});

describe("what the menu is allowed to offer", () => {
  it("narrows to the kind asked for, not the kind asked for a keystroke ago", () => {
    // `#task:` names one kind, so a wiki left on screen from `#ven` is not
    // something Enter can land on.
    const stale = [
      { entity_type: SearchEntityType.wiki, entity_id: 1, title: "Vendors" },
      { entity_type: SearchEntityType.task, entity_id: 2, title: "Vendor call" },
    ];
    const wanted = activeMention("#task:ven")?.types;
    expect(wanted).toEqual([SearchEntityType.task]);
    expect(stale.filter((s) => !wanted || wanted.includes(s.entity_type))).toEqual([stale[1]]);
  });

  it("offers every kind while nothing has been narrowed to", () => {
    const wanted = activeMention("#ven")?.types;
    expect(wanted).toBeNull();
  });
});
