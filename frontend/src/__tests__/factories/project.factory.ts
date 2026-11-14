import {
  ActorKind,
  type ProjectRead,
  type TaskStatusCategory,
  type TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";

import { ownerCan } from "./can";
import { buildDefaultTaskTypes } from "./taskType.factory";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildProjectTaskStatus(overrides: Partial<TaskStatusRead> = {}): TaskStatusRead {
  counter++;
  return {
    id: counter,
    project_id: 1,
    name: `Status ${counter}`,
    category: "todo" as TaskStatusCategory,
    position: counter - 1,
    is_default: false,
    color: "#FBBF24",
    icon: "circle-pause",
    ...overrides,
  };
}

const CATEGORY_VISUALS: Record<TaskStatusCategory, { color: string; icon: string }> = {
  backlog: { color: "#94A3B8", icon: "circle-dashed" },
  todo: { color: "#94A3B8", icon: "circle" },
  in_progress: { color: "#60A5FA", icon: "circle-play" },
  done: { color: "#34D399", icon: "circle-check" },
};

/**
 * Returns the default task statuses that are created for every new project.
 * Accepts a projectId to set the project_id field on each status.
 */
export function buildDefaultTaskStatuses(projectId: number = 1): TaskStatusRead[] {
  const categories: Array<{
    name: string;
    category: TaskStatusCategory;
    isDefault: boolean;
  }> = [
    { name: "To Do", category: "todo", isDefault: true },
    { name: "In Progress", category: "in_progress", isDefault: false },
    { name: "Done", category: "done", isDefault: false },
  ];

  return categories.map((entry, index) => {
    const visuals = CATEGORY_VISUALS[entry.category];
    return buildProjectTaskStatus({
      project_id: projectId,
      name: entry.name,
      category: entry.category,
      position: index,
      is_default: entry.isDefault,
      color: visuals.color,
      icon: visuals.icon,
    });
  });
}

export function buildProject(overrides: Partial<ProjectRead> = {}): ProjectRead {
  counter++;
  const id = overrides.id ?? counter;
  return {
    id,
    name: `Project ${counter}`,
    icon: null,
    description: `Description for project ${counter}`,
    owner_id: 1,
    initiative_id: 1,
    community_id: 1,
    created_by: null,
    created_by_kind: ActorKind.system,
    created_by_install: null,
    start_date: null,
    end_date: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    is_template: false,
    archived_at: null,
    pinned_at: null,
    owner: null,
    owner_plugin: null,
    initiative: null,
    grants: [],
    can: { ...ownerCan(), configure: false },
    task_summary: { total: 0, completed: 0 },
    task_statuses: [],
    // Every project has at least one type; it starts with these four.
    task_types: overrides.task_types ?? buildDefaultTaskTypes(id),
    tags: [],
    properties: [],
    comments_enabled: true,
    ...overrides,
  };
}
