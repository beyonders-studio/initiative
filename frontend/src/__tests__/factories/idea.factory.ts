import type { IdeaRead, IdeaStatusRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

/** A status of the Ideas board, open unless its category says otherwise. */
export function buildIdeaStatus(overrides: Partial<IdeaStatusRead> = {}): IdeaStatusRead {
  counter++;
  return {
    id: counter,
    name: `Status ${counter}`,
    color: "#2563EB",
    icon: "calendar",
    category: "todo",
    ...overrides,
  };
}

/** A published idea as the public reads it. */
export function buildIdea(overrides: Partial<IdeaRead> = {}): IdeaRead {
  counter++;
  const status = overrides.status ?? buildIdeaStatus();
  return {
    task_id: counter,
    title: `Suggestion ${counter}`,
    status,
    votes: 0,
    voted: false,
    closed: status.category === "done",
    created_at: "2026-11-08T00:00:00Z",
    category: null,
    release: null,
    summary: null,
    ...overrides,
  };
}
