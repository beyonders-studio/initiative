/**
 * Links between things, as the one endpoint that serves all of them.
 *
 * The per-tool attach routes — a project's files, an event's files — were the
 * same request with different kinds in it. So is everything here: what varies
 * between attaching a file to a project and a task to an event is which two
 * things are named, and that is an argument.
 */

import {
  type EndpointKind,
  type EndpointRef,
  type RelationshipCreate,
  type RelationshipRead,
  RelationshipType,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createRelationship as createRelationshipRequest,
  removeRelationship as removeRelationshipRequest,
  replaceRelationshipSlice,
} from "@/api/generated/relationships/relationships";

/** A thing, as a reference names it: `task:12`. */
const ref = (end: EndpointRef) => `${end.type}:${end.id}`;

/**
 * Which way a link runs relative to the thing being asked about.
 *
 * `both` is what an attach section wants — a link either way is the same
 * attachment. The two sides are separate questions only for the relations where
 * direction carries meaning: what this page names, and what names it.
 */
export type Direction = "inbound" | "outbound" | "both";

/** Link two things. */
export const relate = async (
  communityId: number,
  source: EndpointRef,
  target: EndpointRef,
  relationshipType: RelationshipType = RelationshipType.attached
): Promise<RelationshipRead> =>
  createRelationshipRequest(communityId, {
    source,
    relationship_type: relationshipType,
    target,
  });

/**
 * Record one edge exactly as stated.
 *
 * The caller has already decided which end is the source — which is the whole
 * of what a directional relation means — so this passes it through rather than
 * assuming, as {@link relate} does, that the anchor describes the pair.
 */
export const createRelationship = (
  communityId: number,
  body: RelationshipCreate
): Promise<RelationshipRead> => createRelationshipRequest(communityId, body);

/** Replace everything of one kind linked to a thing. */
export const setRelated = (
  communityId: number,
  entity: EndpointRef,
  otherType: EndpointKind,
  otherIds: number[],
  relationshipType: RelationshipType = RelationshipType.attached
): Promise<RelationshipRead[]> =>
  replaceRelationshipSlice(communityId, otherIds, {
    entity: ref(entity),
    relationship_type: relationshipType,
    other_type: otherType,
  });

/** Remove a link by its own id. */
export const removeRelationship = (communityId: number, relationshipId: number): Promise<void> =>
  removeRelationshipRequest(communityId, relationshipId);
