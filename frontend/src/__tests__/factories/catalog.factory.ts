import type { CatalogItemRead, CatalogRead } from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;
let imageCounter = 0;

export function resetCounter(): void {
  counter = 0;
  imageCounter = 0;
}

export function buildCatalog(overrides: Partial<CatalogRead> = {}): CatalogRead {
  counter++;
  return {
    id: counter,
    name: `Catalog ${counter}`,
    description: null,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    cover_item_id: null,
    cover: null,
    preview: [],
    archived_at: null,
    can: ownerCan(),
    comments_enabled: true,
    comment_count: 0,
    tags: [],
    properties: [],
    grants: [],
    ...overrides,
  };
}

/**
 * One picture in a catalog. Sized and thumbnailed by default — the shape a
 * real upload has — so the layouts under test reserve space the way they
 * would for a real one.
 */
export function buildCatalogItem(overrides: Partial<CatalogItemRead> = {}): CatalogItemRead {
  imageCounter++;
  return {
    id: imageCounter,
    catalog_id: 1,
    community_id: 1,
    title: `Picture ${imageCounter}`,
    description: null,
    occurred_on: "2026-01-15",
    file_url: `/uploads/1/picture-${imageCounter}.png`,
    thumbnail_url: `/uploads/1/picture-${imageCounter}-thumb.webp`,
    file_content_type: "image/png",
    file_size: 12_345,
    original_filename: `picture-${imageCounter}.png`,
    width: 1200,
    height: 800,
    created_by: 1,
    uploader: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    version_count: 1,
    tags: [],
    properties: [],
    plugin_values: [],
    ...overrides,
  };
}
