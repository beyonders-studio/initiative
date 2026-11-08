import {
  ActorKind,
  type EntityType,
  type TrashItem,
  type TrashListResponse,
} from "@/api/generated/initiativeAPI.schemas";

import { buildPage } from "./page.factory";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTrashItem(overrides: Partial<TrashItem> = {}): TrashItem {
  counter++;
  return {
    entity_type: "task" as EntityType,
    entity_id: counter,
    community_id: 1,
    name: `Item ${counter}`,
    deleted_at: new Date(2026, 3, 20, 10, 0, 0).toISOString(),
    deleted_by_id: 1,
    deleted_by_kind: ActorKind.member,
    deleted_by_display: "Test User",
    purge_at: new Date(2026, 6, 19, 10, 0, 0).toISOString(),
    ...overrides,
  };
}

export function buildTrashListResponse(
  items: TrashItem[] = [],
  overrides: Partial<TrashListResponse> = {}
): TrashListResponse {
  return {
    ...buildPage(items, { page_size: 50 }),
    retention_days: 90,
    ...overrides,
  };
}
