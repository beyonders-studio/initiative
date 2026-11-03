import type {
  GroupingDescription,
  TaskAssigneeSummary,
  TaskListRead,
  TaskListResponse,
  TaskStatusRead,
  TaskTypeRead,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTaskAssignee(
  overrides: Partial<TaskAssigneeSummary> = {}
): TaskAssigneeSummary {
  counter++;
  return {
    id: counter,
    username: `assignee-${counter}`,
    discriminator: 2000 + counter,
    display_name: `Assignee ${counter}`,
    avatar_url: null,
    status: "active",
    ...overrides,
  };
}

export function buildTask(overrides: Partial<TaskListRead> = {}): TaskListRead {
  counter++;

  const defaultStatus: TaskStatusRead = {
    id: 1,
    project_id: 1,
    name: "To Do",
    category: "todo",
    position: 0,
    is_default: true,
    color: "#94A3B8",
    icon: "circle",
  };

  // The project's default type, as every task gets until it is given another.
  const defaultType: TaskTypeRead = {
    id: 1,
    project_id: 1,
    name: "Task",
    position: 0,
    is_default: true,
    color: "#64748B",
    icon: "square-check",
    layout_preset: "plain",
    starting_values: null,
  };

  return {
    id: counter,
    title: `Task ${counter}`,
    description_excerpt: null,
    has_description: false,
    task_status_id: 1,
    task_status: defaultStatus,
    task_type_id: 1,
    task_type: defaultType,
    priority: "medium",
    project_id: 1,
    assignees: [],
    start_date: null,
    due_date: null,
    recurrence: null,
    recurrence_strategy: "fixed",
    recurrence_limit: null,
    recurrence_occurrence_count: 0,
    recurrence_shift: 0,
    recurrence_anchor: null,
    recurrence_anchor_count: 0,
    recurrence_until: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    position: counter,
    archived_at: null,
    created_by: 1,
    comment_count: 0,
    blocked_by_open_count: 0,
    community_id: null,
    community_name: null,
    project_name: null,
    initiative_id: null,
    initiative_name: null,
    initiative_color: null,
    checklist_progress: null,
    parent: null,
    subtask_progress: null,
    completed_at: null,
    tags: [],
    properties: [],
    ...overrides,
  };
}

export function buildTaskListResponse(
  itemsOrOverrides: TaskListRead[] | Partial<TaskListResponse> = {}
): TaskListResponse {
  if (Array.isArray(itemsOrOverrides)) {
    return {
      items: itemsOrOverrides,
      total_count: itemsOrOverrides.length,
      page: 1,
      page_size: 50,
      has_next: false,
      has_prev: false,
      sorting: null,
    };
  }
  return {
    items: [],
    total_count: 0,
    page: 1,
    page_size: 50,
    has_next: false,
    has_prev: false,
    sorting: null,
    ...itemsOrOverrides,
  };
}

/** The task fields the field catalog says a list groups by, as the server's
 *  registry declares them. */
export const TASK_GROUPINGS: GroupingDescription[] = [
  { name: "date_group", kind: "number", bucket: false },
  { name: "priority", kind: "select", bucket: false },
  { name: "task_status_id", kind: "task_status", bucket: false },
  { name: "parent_task_id", kind: "task", bucket: false },
  { name: "assignee_ids", kind: "member", bucket: false },
  { name: "created_by", kind: "member", bucket: false },
  { name: "tag_ids", kind: "tag", bucket: false },
  { name: "project_id", kind: "project", bucket: false },
  { name: "due_date", kind: "date", bucket: true },
  { name: "start_date", kind: "date", bucket: true },
];
