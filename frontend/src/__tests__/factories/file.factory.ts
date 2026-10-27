import { type FileSummary, FileType } from "@/api/generated/initiativeAPI.schemas";
import { FILE_TYPE_KINDS } from "@/lib/fileTypes";

import { ownerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildFileSummary(overrides: Partial<FileSummary> = {}): FileSummary {
  counter++;
  const fileType = overrides.file_type ?? FileType.lexical;
  return {
    id: counter,
    community_id: 1,
    initiative_id: 1,
    name: `File ${counter}`,
    featured_image_url: null,
    is_template: false,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    initiative: null,
    owner: null,
    owner_plugin: null,
    comment_count: 0,
    comments_enabled: true,
    grants: [],
    archived_at: null,
    can: ownerCan(),
    tags: [],
    properties: [],
    file_type: fileType,
    kind: FILE_TYPE_KINDS[fileType],
    file_url: null,
    file_content_type: null,
    file_size: null,
    original_filename: null,
    thumbnail_url: null,
    width: null,
    height: null,
    smart_link_url: null,
    ...overrides,
  };
}
