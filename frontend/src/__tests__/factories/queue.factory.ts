import type {
  QueueItemRead,
  QueueListResponse,
  QueueRead,
  QueueSummary,
} from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildQueueItem(overrides: Partial<QueueItemRead> = {}): QueueItemRead {
  counter++;
  return {
    id: counter,
    queue_id: 1,
    label: `Item ${counter}`,
    position: counter * 10,
    color: null,
    notes: null,
    is_visible: true,
    held_at_round: null,
    user_id: null,
    user: null,
    tags: [],
    properties: [],
    attachment_count: 0,
    created_by: null,
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildQueueSummary(overrides: Partial<QueueSummary> = {}): QueueSummary {
  counter++;
  return {
    id: counter,
    name: `Queue ${counter}`,
    description: null,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    current_round: 1,
    preview: null,
    is_active: false,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    archived_at: null,
    can: ownerCan(),
    tags: [],
    properties: [],
    grants: [],
    comments_enabled: true,
    ...overrides,
  };
}

export function buildQueue(overrides: Partial<QueueRead> = {}): QueueRead {
  counter++;
  return {
    id: counter,
    name: `Queue ${counter}`,
    description: null,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    current_round: 1,
    preview: null,
    is_active: false,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    archived_at: null,
    can: ownerCan(),
    tags: [],
    properties: [],
    items: [],
    current_item_id: null,
    grants: [],
    comments_enabled: true,
    ...overrides,
  };
}

export function buildQueueListResponse(
  itemsOrOverrides: QueueSummary[] | Partial<QueueListResponse> = {}
): QueueListResponse {
  if (Array.isArray(itemsOrOverrides)) {
    return {
      items: itemsOrOverrides,
      total_count: itemsOrOverrides.length,
      page: 1,
      page_size: 20,
      has_next: false,
      has_prev: false,
    };
  }
  return {
    items: [],
    total_count: 0,
    page: 1,
    page_size: 20,
    has_next: false,
    has_prev: false,
    ...itemsOrOverrides,
  };
}
