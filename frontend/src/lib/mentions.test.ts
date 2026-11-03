import { describe, expect, it } from "vitest";

import { FileType, SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import {
  activeMention,
  entityMentionSyntax,
  hasReservedSigil,
  MENTIONABLE_TYPES,
  RESERVED_SIGILS,
  supportsEntityMentions,
  typeForTrigger,
  typeTrigger,
  userMentionSyntax,
} from "@/lib/mentions";

describe("what can be mentioned", () => {
  it("reaches every kind of thing except what people said about them", () => {
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.queue);
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.calendar_event);
    expect(MENTIONABLE_TYPES).toContain(SearchEntityType.dashboard);
    expect(MENTIONABLE_TYPES).not.toContain(SearchEntityType.comment);
  });

  it("gives every kind a trigger word without one being written down", () => {
    for (const type of MENTIONABLE_TYPES) {
      expect(typeForTrigger(typeTrigger(type))).toBe(type);
    }
  });

  // A name is what a mention points at, so it does not also spell one. The
  // backend holds names to the same two characters; this is this side of it.
  it("keeps the two triggers out of a typed name", () => {
    expect(RESERVED_SIGILS).toEqual(["@", "#"]);
    expect(hasReservedSigil("#1 laptop")).toBe(true);
    expect(hasReservedSigil("me@work")).toBe(true);
    expect(hasReservedSigil("Work laptop")).toBe(false);
  });
});

describe("the mention being typed", () => {
  it("offers everything after a bare #, and narrows once a type is named", () => {
    expect(activeMention("see #ven")).toMatchObject({ types: null, query: "ven" });
    expect(activeMention("see #task:ven")).toMatchObject({
      types: [SearchEntityType.task],
      query: "ven",
    });
  });

  it("narrows to a kind that had no trigger of its own before", () => {
    expect(activeMention("see #counter-group:q1")).toMatchObject({
      types: [SearchEntityType.counter_group],
      query: "q1",
    });
  });

  it("reads @ as people and # as things", () => {
    expect(activeMention("hi @al")?.user).toBe(true);
    expect(activeMention("hi #al")?.user).toBe(false);
  });

  it("is not triggered mid-word, so an email address stays an email address", () => {
    expect(activeMention("mail me at sam@example")).toBeNull();
  });

  it("covers the trigger, so replacing it leaves no stray # behind", () => {
    const active = activeMention("see #task:ven");
    expect("see #task:ven".slice(0, "see #task:ven".length - (active?.length ?? 0))).toBe("see ");
  });

  it("ignores a type word that names nothing", () => {
    expect(activeMention("see #nonsense:x")).toBeNull();
  });
});

describe("what gets written into the comment", () => {
  it("writes the kind's own name, so the renderer reads back what it wrote", () => {
    expect(entityMentionSyntax(SearchEntityType.queue, "Intake", 4)).toBe("#queue[Intake](4)");
    expect(entityMentionSyntax(SearchEntityType.counter_group, "Q1", 7)).toBe(
      "#counter-group[Q1](7)"
    );
  });

  it("leaves out of a label the characters the syntax is built from", () => {
    expect(entityMentionSyntax(SearchEntityType.project, "Q[1] (draft)", 9)).toBe(
      "#project[Q1 draft](9)"
    );
    expect(userMentionSyntax("Ada (she/her)", 4)).toBe("@[Ada she/her](4)");
  });
});

describe("where # is offered", () => {
  it("is a standard document and nothing else", () => {
    expect(supportsEntityMentions(FileType.lexical)).toBe(true);
    for (const type of Object.values(FileType)) {
      if (type === FileType.lexical) continue;
      expect(supportsEntityMentions(type)).toBe(false);
    }
  });

  it("is off while the file type is still unknown", () => {
    expect(supportsEntityMentions(null)).toBe(false);
    expect(supportsEntityMentions(undefined)).toBe(false);
  });
});

describe("[[ ]] in a comment", () => {
  it("opens the picker and can make what it does not find", () => {
    const active = activeMention("see [[Road");
    expect(active?.canCreate).toBe(true);
    expect(active?.query).toBe("Road");
    expect(active?.user).toBe(false);
  });

  it("offers as soon as the brackets are typed", () => {
    expect(activeMention("see [[")?.query).toBe("");
  });

  it("covers both brackets, so replacing it leaves none behind", () => {
    const text = "see [[Road";
    const active = activeMention(text);
    expect(text.slice(0, text.length - (active?.length ?? 0))).toBe("see ");
  });

  it("takes a name with spaces in it, which is what a title usually is", () => {
    expect(activeMention("see [[Q1 roadmap")?.query).toBe("Q1 roadmap");
  });

  it("is finished once the brackets are closed", () => {
    expect(activeMention("see [[Roadmap]]")).toBeNull();
  });

  it("does not fire on a single bracket", () => {
    expect(activeMention("an [array")).toBeNull();
  });

  it("leaves # and @ alone, which cannot create", () => {
    expect(activeMention("see #task:ven")?.canCreate).toBe(false);
    expect(activeMention("hi @al")?.canCreate).toBe(false);
  });
});
