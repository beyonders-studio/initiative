/**
 * The graph, from either side of it.
 *
 * These belong to no one tool, because the question they answer is about a pair
 * of things rather than about either: the same hook serves a project's
 * attachments, a task's dependencies and a file's backlinks.
 *
 * The per-tool attach hooks in `useProjects` stay, because they keep a shape
 * their own callers already expect. What is different here is that
 * a write says which tool sits at *each* end and refreshes both.
 */

import { useMemo } from "react";

import {
  type EndpointRef,
  type RelatedEnd,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
  SearchEntityType,
  type Tool,
} from "@/api/generated/initiativeAPI.schemas";
import {
  useGetRelationsNeighbourhood,
  useListRelationships,
} from "@/api/generated/relationships/relationships";
import { invalidate, q } from "@/api/query-keys";
import { createRelationship, removeRelationship, setRelated } from "@/api/relationships";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { idsByKind, type LinkedRef, sameIds } from "@/lib/relationships";
import type { MutationOpts } from "@/types/mutation";

/**
 * Every live edge touching one thing, whichever way it runs.
 *
 * One request, because each row says its own type and the side it runs relative
 * to this thing — so a surface showing seven headings filters one answer rather
 * than asking seven times. See `groupEdges` in `@/lib/relationships`.
 */
export const useRelationshipsFor = (entity: EndpointRef, options?: { enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  const params = {
    entity: `${entity.type}:${entity.id}`,
    relationship_type: null,
    other_type: null,
    direction: "both" as const,
  };
  return useListRelationships(communityId, params, { query: options });
};

/** A tool and which one of them — what a cache entry for the shims is keyed by. */
export interface ToolRef {
  tool: Tool;
  id: number;
}

/** The tool a far end is addressed inside, where it named one. */
const toolRefOf = (end: RelatedEnd): ToolRef | null =>
  end.tool && end.tool_id != null ? { tool: end.tool, id: end.tool_id } : null;

/**
 * What changing a link invalidates: the graph, and the tool at each end of it.
 *
 * Both ends, because a link is a fact about a pair and several tools still
 * serialise their own side of one — a project lists its files, a file
 * lists its projects. Those shapes read
 * differently the moment an edge moves, whichever end was clicked.
 */
const invalidateEdge = (...ends: (ToolRef | null | undefined)[]) =>
  invalidate(
    q.relationships(),
    ...ends.filter((end): end is ToolRef => Boolean(end)).map((end) => q.tool(end.tool, end.id))
  );

/**
 * Record one edge.
 *
 * Takes the edge already stated as source → target: which end is the source is
 * the whole of what a directional relation means, and `edgeFor` in
 * `@/lib/relationships` is what decides it.
 */
export const useRelate = (
  anchor?: ToolRef | null,
  options?: MutationOpts<RelationshipRead, RelationshipCreate>
) =>
  useCommunityMutation<RelationshipRead, RelationshipCreate>(
    {
      mutationFn: (communityId, body) => createRelationship(communityId, body),
      invalidate: (data) => invalidateEdge(anchor, toolRefOf(data.other)),
      errorKey: "relations:addError",
    },
    options
  );

/** An edge to take back: the row, so the far end's tool is refreshed too, or
 *  its id alone where the far end is in the anchor's own tool. */
type UnrelatedEdge = Pick<RelationshipRead, "id"> & Partial<Pick<RelationshipRead, "other">>;

/**
 * Take one edge back.
 */
export const useUnrelate = (anchor?: ToolRef | null, options?: MutationOpts<void, UnrelatedEdge>) =>
  useCommunityMutation<void, UnrelatedEdge>(
    {
      mutationFn: (communityId, row) => removeRelationship(communityId, row.id),
      invalidate: (_data, row) => invalidateEdge(anchor, row.other ? toolRefOf(row.other) : null),
      errorKey: "relations:removeError",
    },
    options
  );

/** How far out the graph will walk. The endpoint refuses further. */
export const MAX_HOPS = 3;

/** One thing in a neighbourhood, and how many hops out it was found. */
export interface GraphNode {
  ref: EndpointRef;
  end: RelatedEnd;
  depth: number;
}

/** One link in a neighbourhood, as the pair of things it joins. */
export interface GraphEdge {
  id: number;
  from: string;
  to: string;
  relationship_type: RelationshipRead["relationship_type"];
  direction: string;
  provenance: string;
}

export interface Neighbourhood {
  nodes: GraphNode[];
  edges: GraphEdge[];
  isLoading: boolean;
  /** The walk further out failed, and this is the one hop the list holds. */
  walkFailed: boolean;
}

const keyOf = (ref: EndpointRef) => `${ref.type}:${ref.id}`;

/**
 * Everything within `hops` of one thing.
 *
 * One hop is the list of the thing's own links, which the section around the
 * graph already holds, so it is not asked for twice. Further out is one request
 * for the whole walk: the server goes a hop at a time, a batch per hop, and
 * gates each edge and far end as the list does. Asking per neighbour instead
 * cost a request for every thing found, and labels — shared by everything
 * carrying them — made that dozens.
 *
 * Labels are left out unless asked for, and left out of the *walk* rather than
 * the drawing: walking through one reaches the whole community in a hop, so
 * leaving it in the walk and out of the picture would be the worst of both.
 *
 * A walk that fails falls back to the one hop the list already holds, so the
 * picture and its controls stay up and the reader can step back in.
 */
export const useRelationsNeighbourhood = (
  entity: EndpointRef,
  hops: number,
  options?: { enabled?: boolean; includeTags?: boolean }
): Neighbourhood => {
  const communityId = useActiveCommunityId();
  const enabled = options?.enabled ?? true;
  const includeTags = options?.includeTags ?? false;
  const walks = hops >= 2;
  const centre = keyOf(entity);

  const near = useRelationshipsFor(entity, { enabled });

  const params = { entity: centre, hops, include_tags: includeTags };
  const far = useGetRelationsNeighbourhood(communityId, params, {
    query: { enabled: enabled && walks },
  });

  const walkFailed = walks && far.isError;

  return useMemo(() => {
    if (walks && !walkFailed) {
      return {
        nodes: (far.data?.nodes ?? []).map((node) => ({
          ref: { type: node.end.type, id: node.end.id },
          end: node.end,
          depth: node.depth,
        })),
        edges: (far.data?.edges ?? []).map((edge) => ({
          id: edge.id,
          from: keyOf(edge.anchor),
          to: keyOf(edge.other),
          relationship_type: edge.relationship_type,
          direction: edge.direction,
          provenance: edge.provenance,
        })),
        isLoading: far.isLoading,
        walkFailed: false,
      };
    }

    const rows = (near.data ?? []).filter(
      (row) =>
        includeTags ||
        (row.relationship_type !== RelationshipType.tagged_with &&
          row.other.type !== SearchEntityType.tag)
    );
    const nodes = new Map<string, GraphNode>();
    for (const row of rows) {
      const ref = { type: row.other.type, id: row.other.id };
      nodes.set(keyOf(ref), { ref, end: row.other, depth: 1 });
    }
    return {
      nodes: [...nodes.values()],
      edges: rows.map((row) => ({
        id: row.id,
        from: centre,
        to: keyOf(row.other),
        relationship_type: row.relationship_type,
        direction: row.direction,
        provenance: row.provenance,
      })),
      isLoading: near.isLoading,
      walkFailed,
    };
  }, [walks, walkFailed, far.data, far.isLoading, near.data, near.isLoading, includeTags, centre]);
};

/** The links an item is set to have, of every kind. */
interface ItemLinks {
  /** The item, which the tool `useSetItemLinks` was given holds. */
  item: EndpointRef;
  links: LinkedRef[];
  /** What it was last set to, so only the kinds that moved are written. */
  previous: LinkedRef[];
  /**
   * Write every kind, even one whose set of ids has not moved: for a retry,
   * where the kind that failed still reads as unchanged against what was
   * asked the first time.
   */
  force?: boolean;
}

/**
 * Set everything an item is linked to, whatever kinds those are: one slice of
 * links per kind, which is the shape the endpoint is built for. A kind is
 * written only when its set of ids differs, and a kind that has lost all its
 * links is written as an empty set, so removing the last of a kind sticks.
 */
export const useSetItemLinks = (
  tool: Tool,
  toolId: number,
  options?: MutationOpts<void, ItemLinks>
) =>
  useCommunityMutation<void, ItemLinks>(
    {
      mutationFn: async (communityId, { item, links, previous, force }) => {
        const wanted = idsByKind(links);
        const had = idsByKind(previous);
        for (const kind of new Set([...wanted.keys(), ...had.keys()])) {
          const next = wanted.get(kind) ?? [];
          if (!force && sameIds(next, had.get(kind) ?? [])) continue;
          await setRelated(communityId, item, kind, next);
        }
      },
      invalidate: () => invalidate(q.tool(tool, toolId)),
      errorKey: "relations:addError",
    },
    options
  );
