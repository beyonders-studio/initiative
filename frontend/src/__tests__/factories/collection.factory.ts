import type { CollectionFileSummary, CollectionRead } from "@/api/generated/initiativeAPI.schemas";

import { buildFileSummary } from "./file.factory";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** A collection in Files, which the reader may change, holding one file they
 *  can open. */
export function buildCollection(overrides: Partial<CollectionRead> = {}): CollectionRead {
  counter++;
  return {
    id: counter,
    initiative_id: 1,
    community_id: 1,
    name: `Collection ${counter}`,
    description: null,
    cover_file_id: null,
    cover: null,
    file_count: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    archived_at: null,
    comments_enabled: true,
    comments_locked_at: null,
    comment_count: 0,
    tags: [],
    properties: [],
    fields: [],
    can: { edit: true, unarchive: false },
    ...overrides,
  };
}

/** A file as its collection lists it: added to it when it was made, holding
 *  no values of the collection's fields. */
export function buildCollectionFile(
  overrides: Partial<CollectionFileSummary> = {}
): CollectionFileSummary {
  const file = buildFileSummary(overrides);
  return { ...file, added_at: file.created_at, fields: [], ...overrides };
}
