import type { ShareRequestRead, ShareStanding } from "@/api/generated/initiativeAPI.schemas";

import { buildUserSummary } from "./user.factory";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** A request waiting on the reader's answer: somebody who is not a guest
 *  asking to view a file, with no note. */
export function buildShareRequest(overrides: Partial<ShareRequestRead> = {}): ShareRequestRead {
  counter++;
  return {
    id: counter,
    batch_id: `00000000-0000-4000-8000-${String(counter).padStart(12, "0")}`,
    resource_type: "file",
    resource_id: 1,
    resource_name: `File ${counter}`,
    initiative_id: 1,
    user: buildUserSummary(),
    guest_until: null,
    level: "read",
    message: null,
    created_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

/** Where the reader stands on a file they know is there and cannot open, and
 *  have not asked for. */
export function buildShareStanding(overrides: Partial<ShareStanding> = {}): ShareStanding {
  return {
    resource_type: "file",
    resource_id: 1,
    initiative_id: 1,
    level: null,
    pending: null,
    ...overrides,
  };
}
