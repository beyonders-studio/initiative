import type { DataJobRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** A queued task-list PDF export unless ``overrides`` say otherwise; pass
 * ``direction: "import"`` (and a ``source``) for an import job. */
export function buildDataJob(overrides: Partial<DataJobRead> = {}): DataJobRead {
  counter++;
  return {
    id: counter,
    community_id: 1,
    direction: "export",
    created_by: 1,
    source: "tasks",
    params: {},
    status: "queued",
    error: null,
    expires_at: null,
    created_at: "2026-07-12T00:00:00Z",
    updated_at: "2026-07-12T00:00:00Z",
    plan: null,
    result: null,
    template_id: "task-table",
    format: "pdf",
    delivered: false,
    ...overrides,
  };
}
