/**
 * How a relation reads to a person, and which edge asserting one writes.
 *
 * The database stores one direction and the API renders every edge from the side
 * that asked, so which way a relation runs is a presentation question — and this
 * is the only place that answers it. A component asks for a group and is told
 * what to call it, what to draw beside it, and what to POST; it never decides
 * that `depends_on` outbound is the blocked end.
 *
 * Two of the six primitives are absent on purpose. `tagged_with` keeps its own
 * tag picker — a label is not something you pick a relationship type for. And
 * `references` is derived: it is read out of a body when that body is saved, so
 * it is shown and never asserted. `SUBTYPES` ships empty server-side, so there
 * is no finer word to choose yet.
 */

import {
  ArrowUpRight,
  Ban,
  Blocks,
  type LucideIcon,
  Package,
  Paperclip,
  Quote,
  Link2 as Related,
  Shapes,
  Tag,
} from "lucide-react";

import {
  type EndpointRef,
  type RelatedEnd,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
  type SearchEntityType,
  SearchEntityType as SearchEntityTypeValues,
} from "@/api/generated/initiativeAPI.schemas";
import type { Direction } from "@/api/relationships";
import type { SearchTarget } from "@/lib/searchResults";

/** The groups a relations surface can show, each its own heading. */
export type RelationGroupKey =
  | "attached"
  | "related"
  | "blockedBy"
  | "blocks"
  | "partOf"
  | "parts"
  | "referencedBy"
  | "references"
  | "tagged";

export interface RelationGroup {
  key: RelationGroupKey;
  relationshipType: RelationshipType;
  /**
   * Which side of the anchor this group lists. `both` is for the symmetric
   * relations, where an edge either way is the same fact.
   */
  direction: Direction;
  /** Whether a person may add to this group, or only read it. */
  assertable: boolean;
  icon: LucideIcon;
}

/**
 * Every group, keyed. The two directional primitives appear twice — once per
 * side — because "what blocks this" and "what this blocks" are different
 * questions with different answers, and a heading that served both would have to
 * be vague enough to be useless.
 */
export const RELATION_GROUPS: Record<RelationGroupKey, RelationGroup> = {
  attached: {
    key: "attached",
    relationshipType: RelationshipType.attached,
    direction: "both",
    assertable: true,
    icon: Paperclip,
  },
  related: {
    key: "related",
    relationshipType: RelationshipType.related_to,
    direction: "both",
    assertable: true,
    icon: Related,
  },
  blockedBy: {
    key: "blockedBy",
    relationshipType: RelationshipType.depends_on,
    direction: "outbound",
    assertable: true,
    icon: Ban,
  },
  blocks: {
    key: "blocks",
    relationshipType: RelationshipType.depends_on,
    direction: "inbound",
    assertable: true,
    icon: Blocks,
  },
  partOf: {
    key: "partOf",
    relationshipType: RelationshipType.part_of,
    direction: "outbound",
    assertable: true,
    icon: Package,
  },
  parts: {
    key: "parts",
    relationshipType: RelationshipType.part_of,
    direction: "inbound",
    assertable: true,
    icon: Shapes,
  },
  referencedBy: {
    key: "referencedBy",
    relationshipType: RelationshipType.references,
    direction: "inbound",
    assertable: false,
    icon: Quote,
  },
  /** What this thing mentions: the other side of `referencedBy`. */
  references: {
    key: "references",
    relationshipType: RelationshipType.references,
    direction: "outbound",
    assertable: false,
    icon: ArrowUpRight,
  },
  /**
   * Labels. Deliberately absent from {@link RELATION_GROUP_ORDER}, so no list
   * of links grows a Tags heading — a thing's tags are shown and picked where
   * tags belong. It exists for the one surface that may want them anyway: a
   * graph, where a shared label is a real path between two things.
   */
  tagged: {
    key: "tagged",
    relationshipType: RelationshipType.tagged_with,
    direction: "outbound",
    assertable: false,
    icon: Tag,
  },
};

/**
 * The order groups are shown in: what this thing holds, then what stands in its
 * way, then how it sits in a larger whole, then what it mentions and what
 * mentions it. Read top to bottom that is decreasing urgency, which is the
 * order somebody opening a task wants them.
 */
export const RELATION_GROUP_ORDER: RelationGroupKey[] = [
  "attached",
  "blockedBy",
  "blocks",
  "partOf",
  "parts",
  "related",
  "references",
  "referencedBy",
];

/** The groups a person may add to, in display order. */
export const ASSERTABLE_GROUPS: RelationGroup[] = RELATION_GROUP_ORDER.map(
  (key) => RELATION_GROUPS[key]
).filter((group) => group.assertable);

/**
 * The kinds that are a thing you attach rather than a thing you depend on.
 *
 * A file or a picture is almost always evidence about the work rather than
 * a step in it, so a link touching one reads as "attached" unless somebody says
 * otherwise.
 */
const FILE_LIKE: ReadonlySet<SearchEntityType> = new Set([
  SearchEntityTypeValues.file,
  SearchEntityTypeValues.catalog_item,
]);

/**
 * The link to offer first, given what was picked.
 *
 * The dialog asks for the thing before it asks what the link says, so by the
 * time this is consulted both ends are known and the common case can be
 * answered for the reader. What it answers is deliberately the least committal
 * reading that is still accurate:
 *
 * **It never proposes a dependency.** "Blocked by" is a claim with consequences
 * — it shows on the board, it counts, it says somebody is waiting — and it is
 * not one to assert on a reader's behalf because they picked a task. Leaving
 * the sentence saying something harmless but not quite right is also what
 * teaches people the verb is theirs to change; a guess that happens to be right
 * teaches nothing, and a guess that is wrong is worse than a default.
 * {@link groupOrderFor} promotes it in the list instead, where choosing it is
 * one click and still a choice.
 */
export const defaultGroupFor = (
  anchor: SearchEntityType,
  picked: SearchEntityType
): RelationGroupKey => {
  if (FILE_LIKE.has(picked) || FILE_LIKE.has(anchor)) return "attached";
  if (anchor === picked) return "related";
  return "attached";
};

/**
 * The order to offer links in for this pair of things.
 *
 * Only the order changes — every group a reader may assert is still in the
 * list. Two things of the same kind are usually sequenced rather than filed, so
 * the dependency pair rises to where it can be found without reading the whole
 * menu.
 */
export const groupOrderFor = (
  anchor: SearchEntityType,
  picked: SearchEntityType,
  groups: RelationGroup[]
): RelationGroup[] => {
  const promoted: RelationGroupKey[] =
    anchor === picked && !FILE_LIKE.has(anchor) ? ["blockedBy", "blocks"] : [];
  const rank = (group: RelationGroup) => {
    const index = promoted.indexOf(group.key);
    return index === -1 ? promoted.length : index;
  };
  return [...groups].sort((a, b) => rank(a) - rank(b));
};

/**
 * The edge a group asserts, written as the API takes it.
 *
 * A group listing the *inbound* side is asserted from the far end: "this task
 * blocks that one" is the fact that *that one* depends on this. Storing it the
 * other way round would record the opposite of what was asked, which is the one
 * thing this module exists to get right.
 *
 * A symmetric relation names the anchor as source, and the server normalises the
 * pair into node-id order — so it does not matter which end is given.
 */
export const edgeFor = (
  group: RelationGroup,
  anchor: EndpointRef,
  other: EndpointRef
): RelationshipCreate =>
  group.direction === "inbound"
    ? { source: other, relationship_type: group.relationshipType, target: anchor }
    : { source: anchor, relationship_type: group.relationshipType, target: other };

/**
 * Whether this link is the anchor's to make, given what was picked.
 *
 * A group listing the *inbound* side asserts its edge from the far end — "this
 * blocks that" is the fact that *that* depends on this — and a relation that
 * describes its source is the source's to assert. So those groups need the
 * picked thing to be one the reader may change, not merely one they may open.
 *
 * A symmetric group describes neither end and asks only that both be readable,
 * which having found it in the picker already proved.
 */
export const canAssert = (group: RelationGroup, otherIsWritable: boolean): boolean =>
  group.direction !== "inbound" || otherIsWritable;

/**
 * Which shown group an edge belongs to, or null when none of them claims it.
 *
 * One request asks for every edge touching a thing, and each row carries its own
 * type and the side it runs relative to that thing — so the headings are filters
 * over one answer rather than a request each. A symmetric group takes an edge
 * either way, because for those the two directions are the same fact.
 */
export const groupOf = (
  row: Pick<RelationshipRead, "relationship_type" | "direction">,
  groups: RelationGroup[]
): RelationGroup | null =>
  groups.find(
    (group) =>
      group.relationshipType === row.relationship_type &&
      (group.direction === "both" || group.direction === row.direction)
  ) ?? null;

/** A page of edges split into the groups being shown, in display order. */
export const groupEdges = <T extends Pick<RelationshipRead, "relationship_type" | "direction">>(
  rows: T[],
  groups: RelationGroup[]
): Map<RelationGroupKey, T[]> => {
  const grouped = new Map<RelationGroupKey, T[]>(groups.map((group) => [group.key, []]));
  for (const row of rows) {
    const group = groupOf(row, groups);
    if (group) grouped.get(group.key)?.push(row);
  }
  return grouped;
};

/**
 * A far end as the search helpers take it.
 *
 * `hitIcon` and `searchHitPath` already know how every kind is drawn and
 * addressed — including that a task is reached through its project and a picture
 * through its catalog. An edge's far end carries the same five facts under its
 * own names, so it is adapted rather than having that knowledge restated here.
 */
export const relatedTarget = (end: RelatedEnd): SearchTarget => ({
  entity_type: end.type,
  entity_id: end.id,
  initiative_id: end.initiative_id,
  tool: end.tool,
  tool_id: end.tool_id,
});

/** One linked thing, as a compact chip or form value needs it. */
export interface LinkedRef {
  type: SearchEntityType;
  id: number;
  title: string | null;
  /**
   * What the thing it lives in is called — the project a task sits in, the
   * wiki a page sits in. Optional because it is only ever shown: a caller that
   * has a title and nothing else still names a thing, it just names it less
   * clearly when two of them share a name.
   */
  toolTitle?: string | null;
}

/** A linked thing as a reference spells it — `task:12`, and a stable list key. */
export const refKey = (ref: Pick<LinkedRef, "type" | "id">) => `${ref.type}:${ref.id}`;

/** The ids in a set of links, grouped by kind. */
export const idsByKind = (rows: LinkedRef[]): Map<SearchEntityType, number[]> => {
  const map = new Map<SearchEntityType, number[]>();
  for (const row of rows) {
    map.set(row.type, [...(map.get(row.type) ?? []), row.id]);
  }
  return map;
};

/** Whether two id lists name the same things, whatever order they arrived in. */
export const sameIds = (a: number[], b: number[]) =>
  a.length === b.length && [...a].sort().join(",") === [...b].sort().join(",");
