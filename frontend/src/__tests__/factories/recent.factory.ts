import type { PersonalItemRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetRecentCounter(): void {
  counter = 0;
}

/**
 * Build a generic recent-item for use in tests. Caller can override
 * ``entity_type`` and any other field. Use the type-specific helpers below
 * for ergonomic factories.
 */
export function buildRecentItem(overrides: Partial<PersonalItemRead> = {}): PersonalItemRead {
  counter++;
  return {
    entity_type: "project",
    entity_id: counter,
    community_id: 1,
    initiative_id: 5,
    name: `Recent Item ${counter}`,
    viewed_at: new Date().toISOString(),
    bookmarked_at: null,
    icon: null,
    file_type: null,
    mime_type: null,
    original_filename: null,
    ...overrides,
  };
}

export function buildRecentProjectItem(
  overrides: Partial<PersonalItemRead> = {}
): PersonalItemRead {
  return buildRecentItem({ entity_type: "project", icon: "🛠", ...overrides });
}

export function buildRecentFileItem(overrides: Partial<PersonalItemRead> = {}): PersonalItemRead {
  return buildRecentItem({
    entity_type: "file",
    file_type: "lexical",
    ...overrides,
  });
}

export function buildRecentQueueItem(overrides: Partial<PersonalItemRead> = {}): PersonalItemRead {
  return buildRecentItem({ entity_type: "queue", ...overrides });
}

export function buildRecentCounterGroupItem(
  overrides: Partial<PersonalItemRead> = {}
): PersonalItemRead {
  return buildRecentItem({ entity_type: "counter_group", ...overrides });
}
