import { describe, expect, it } from "vitest";

import {
  type RelatedEnd,
  RelationshipType,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import {
  ASSERTABLE_GROUPS,
  canAssert,
  defaultGroupFor,
  edgeFor,
  groupEdges,
  groupOf,
  groupOrderFor,
  idsByKind,
  RELATION_GROUP_ORDER,
  RELATION_GROUPS,
  refKey,
  relatedTarget,
  sameIds,
} from "@/lib/relationships";

const anchor = { type: SearchEntityType.task, id: 1 };
const other = { type: SearchEntityType.task, id: 2 };

const edge = (relationship_type: RelationshipType, direction: "inbound" | "outbound") => ({
  relationship_type,
  direction,
});

describe("edgeFor", () => {
  it("asserts an outbound group with the anchor as the source", () => {
    // "this task is blocked by that one" is this one depending on that one.
    expect(edgeFor(RELATION_GROUPS.blockedBy, anchor, other)).toEqual({
      source: anchor,
      relationship_type: RelationshipType.depends_on,
      target: other,
    });
  });

  it("asserts an inbound group from the far end", () => {
    // "this task blocks that one" is the fact that THAT one depends on this.
    // Storing it the other way round would record the opposite of what was
    // asked, which is the whole reason this function exists.
    expect(edgeFor(RELATION_GROUPS.blocks, anchor, other)).toEqual({
      source: other,
      relationship_type: RelationshipType.depends_on,
      target: anchor,
    });
  });

  it("turns the pair round for parts, as it does for blocks", () => {
    expect(edgeFor(RELATION_GROUPS.partOf, anchor, other).source).toEqual(anchor);
    expect(edgeFor(RELATION_GROUPS.parts, anchor, other).source).toEqual(other);
  });

  it("names the anchor as the source of a symmetric relation", () => {
    // Which end is given does not matter: the server stores the pair in node-id
    // order whichever way it arrives.
    for (const group of [RELATION_GROUPS.attached, RELATION_GROUPS.related]) {
      expect(edgeFor(group, anchor, other).source).toEqual(anchor);
    }
  });
});

describe("groupOf", () => {
  const groups = RELATION_GROUP_ORDER.map((key) => RELATION_GROUPS[key]);

  it("splits a directional relation by the side it runs", () => {
    expect(groupOf(edge(RelationshipType.depends_on, "outbound"), groups)?.key).toBe("blockedBy");
    expect(groupOf(edge(RelationshipType.depends_on, "inbound"), groups)?.key).toBe("blocks");
  });

  it("claims a symmetric relation whichever way it runs", () => {
    expect(groupOf(edge(RelationshipType.attached, "inbound"), groups)?.key).toBe("attached");
    expect(groupOf(edge(RelationshipType.attached, "outbound"), groups)?.key).toBe("attached");
  });

  it("claims nothing for a relation no shown group covers", () => {
    // A tag is stored as an edge but is picked with the tag picker, so no
    // heading here answers for one.
    expect(groupOf(edge(RelationshipType.tagged_with, "outbound"), groups)).toBeNull();
  });

  it("claims nothing when the group that would take it is not shown", () => {
    expect(
      groupOf(edge(RelationshipType.depends_on, "inbound"), [RELATION_GROUPS.attached])
    ).toBeNull();
  });
});

describe("groupEdges", () => {
  it("puts every edge under its own heading and keeps the empty ones", () => {
    const groups = [RELATION_GROUPS.attached, RELATION_GROUPS.blockedBy, RELATION_GROUPS.blocks];
    const grouped = groupEdges(
      [
        edge(RelationshipType.attached, "outbound"),
        edge(RelationshipType.depends_on, "outbound"),
        edge(RelationshipType.depends_on, "inbound"),
        edge(RelationshipType.depends_on, "inbound"),
        edge(RelationshipType.tagged_with, "outbound"),
      ],
      groups
    );

    expect(grouped.get("attached")).toHaveLength(1);
    expect(grouped.get("blockedBy")).toHaveLength(1);
    expect(grouped.get("blocks")).toHaveLength(2);
    // A heading that was asked for but matched nothing is still a key, so a
    // caller can tell "no edges" from "not shown".
    expect(grouped.has("related")).toBe(false);
  });
});

describe("the vocabulary", () => {
  it("offers only what a person may assert", () => {
    // `references` is read out of a body on save, so it is shown and never
    // offered; `tagged_with` has the tag picker.
    const offered = ASSERTABLE_GROUPS.map((group) => group.relationshipType);
    expect(offered).not.toContain(RelationshipType.references);
    expect(offered).not.toContain(RelationshipType.tagged_with);
    expect(new Set(offered)).toEqual(
      new Set([
        RelationshipType.attached,
        RelationshipType.depends_on,
        RelationshipType.part_of,
        RelationshipType.related_to,
      ])
    );
  });

  it("shows references, so a body's mentions are readable", () => {
    expect(RELATION_GROUPS.referencedBy.assertable).toBe(false);
    expect(RELATION_GROUP_ORDER).toContain("referencedBy");
  });
});

describe("canAssert", () => {
  it("lets a symmetric link be made with anything you can open", () => {
    // It describes neither end, so it changes neither — finding it in the
    // picker is the whole of what it asks.
    expect(canAssert(RELATION_GROUPS.attached, false)).toBe(true);
    expect(canAssert(RELATION_GROUPS.related, false)).toBe(true);
  });

  it("lets an outbound link be made with anything you can open", () => {
    // "This is blocked by that" describes *this*, which is already yours.
    expect(canAssert(RELATION_GROUPS.blockedBy, false)).toBe(true);
    expect(canAssert(RELATION_GROUPS.partOf, false)).toBe(true);
  });

  it("asks that a reversed link's far end be yours to change", () => {
    // "This blocks that" is stored as *that* depending on this, so it is a
    // statement about that one — and the server will only take it from
    // somebody who may change it.
    expect(canAssert(RELATION_GROUPS.blocks, false)).toBe(false);
    expect(canAssert(RELATION_GROUPS.parts, false)).toBe(false);
    expect(canAssert(RELATION_GROUPS.blocks, true)).toBe(true);
    expect(canAssert(RELATION_GROUPS.parts, true)).toBe(true);
  });
});

describe("relatedTarget", () => {
  it("renames a far end's five facts into what the search helpers read", () => {
    const end: RelatedEnd = {
      type: SearchEntityType.task,
      id: 7,
      title: "Ship it",
      initiative_id: 3,
      updated_at: null,
      tool: Tool.project,
      tool_id: 11,
      tool_title: null,
      image_urls: [],
      icon: null,
      color: null,
      file_type: null,
      mime_type: null,
      original_filename: null,
      smart_link_url: null,
      is_open: null,
    };
    expect(relatedTarget(end)).toEqual({
      entity_type: SearchEntityType.task,
      entity_id: 7,
      initiative_id: 3,
      tool: Tool.project,
      tool_id: 11,
    });
  });
});

describe("comparing sets of links", () => {
  it("reads a reorder as no change", () => {
    // The old queue dialog compared these position by position, so reordering
    // the same files counted as a change and a straight swap did not.
    expect(sameIds([1, 2, 3], [3, 1, 2])).toBe(true);
    expect(sameIds([1, 2], [1, 3])).toBe(false);
    expect(sameIds([1], [1, 2])).toBe(false);
    expect(sameIds([], [])).toBe(true);
  });

  it("groups ids by kind", () => {
    const grouped = idsByKind([
      { type: SearchEntityType.file, id: 1, title: null },
      { type: SearchEntityType.task, id: 2, title: null },
      { type: SearchEntityType.file, id: 3, title: null },
    ]);
    expect(grouped.get(SearchEntityType.file)).toEqual([1, 3]);
    expect(grouped.get(SearchEntityType.task)).toEqual([2]);
  });

  it("spells a reference the way the API does", () => {
    expect(refKey({ type: SearchEntityType.task, id: 12 })).toBe("task:12");
  });

  describe("what the dialog proposes once something is picked", () => {
    it("reads a file or a picture as something attached", () => {
      expect(defaultGroupFor(SearchEntityType.task, SearchEntityType.file)).toBe("attached");
      expect(defaultGroupFor(SearchEntityType.file, SearchEntityType.task)).toBe("attached");
      expect(defaultGroupFor(SearchEntityType.project, SearchEntityType.library_item)).toBe(
        "attached"
      );
    });

    it("reads two things of one kind as merely related", () => {
      expect(defaultGroupFor(SearchEntityType.task, SearchEntityType.task)).toBe("related");
      expect(defaultGroupFor(SearchEntityType.project, SearchEntityType.project)).toBe("related");
    });

    it("NEVER proposes a dependency", () => {
      // "Blocked by" shows on the board, counts, and says somebody is waiting.
      // It is not a claim to make on a reader's behalf because they picked a
      // task, and a sentence that is visibly not quite right is what teaches
      // them the verb is theirs to change.
      const kinds = Object.values(SearchEntityType);
      for (const anchor of kinds) {
        for (const picked of kinds) {
          const proposed = defaultGroupFor(anchor, picked);
          expect(proposed).not.toBe("blockedBy");
          expect(proposed).not.toBe("blocks");
        }
      }
    });

    it("proposes something a reader is actually offered", () => {
      const assertable = ASSERTABLE_GROUPS.map((group) => group.key);
      for (const anchor of Object.values(SearchEntityType)) {
        for (const picked of Object.values(SearchEntityType)) {
          expect(assertable).toContain(defaultGroupFor(anchor, picked));
        }
      }
    });
  });

  describe("the order the links are offered in", () => {
    it("promotes the dependency pair for two things of one kind", () => {
      const ordered = groupOrderFor(
        SearchEntityType.task,
        SearchEntityType.task,
        ASSERTABLE_GROUPS
      );
      expect(ordered.slice(0, 2).map((group) => group.key)).toEqual(["blockedBy", "blocks"]);
    });

    it("leaves a mixed pair in the order the surface set", () => {
      const ordered = groupOrderFor(
        SearchEntityType.task,
        SearchEntityType.file,
        ASSERTABLE_GROUPS
      );
      expect(ordered.map((group) => group.key)).toEqual(
        ASSERTABLE_GROUPS.map((group) => group.key)
      );
    });

    it("takes nothing away, whatever the pair", () => {
      const every = new Set(ASSERTABLE_GROUPS.map((group) => group.key));
      for (const anchor of Object.values(SearchEntityType)) {
        const ordered = groupOrderFor(anchor, SearchEntityType.task, ASSERTABLE_GROUPS);
        expect(new Set(ordered.map((group) => group.key))).toEqual(every);
      }
    });
  });
});
