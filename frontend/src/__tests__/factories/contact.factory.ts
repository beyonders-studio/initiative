import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildContact(overrides: Partial<ContactRead> = {}): ContactRead {
  counter++;
  return {
    id: counter,
    name: `Contact ${counter}`,
    is_organization: false,
    emails: [],
    phones: [],
    addresses: [],
    websites: [],
    organization: null,
    initiative_id: 1,
    community_id: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    archived_at: null,
    can: ownerCan(),
    comments_enabled: true,
    tags: [],
    properties: [],
    grants: [],
    ...overrides,
  };
}
