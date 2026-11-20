import { HttpResponse } from "msw";

import {
  buildDefaultTaskStatuses,
  buildDefaultTaskTypes,
  buildTask,
  buildTaskListResponse,
  TASK_GROUPINGS,
} from "@/__tests__/factories";

import { communityHttp } from "../communityHttp";

export const taskHandlers = [
  communityHttp.get("/tasks/", () => {
    return HttpResponse.json(buildTaskListResponse());
  }),

  // A list grouped by anything has no groups until a test says what they are.
  communityHttp.get("/tasks/groups", () => HttpResponse.json({ groups: [], rows: {} })),

  communityHttp.get("/fields/tasks", () =>
    HttpResponse.json({
      dataset: "tasks",
      fields: [],
      relations: [],
      default_filters: [],
      groupings: TASK_GROUPINGS,
    })
  ),

  communityHttp.get("/tasks/autocomplete", () => {
    return HttpResponse.json(
      buildTaskListResponse().items.map((task) => ({ id: task.id, title: task.title }))
    );
  }),

  communityHttp.patch("/tasks/:id", () => {
    return HttpResponse.json(buildTask());
  }),

  communityHttp.get("/projects/:id/task-statuses/", () => {
    return HttpResponse.json(buildDefaultTaskStatuses());
  }),

  communityHttp.get("/projects/:id/task-types/", ({ params }) => {
    return HttpResponse.json(buildDefaultTaskTypes(Number(params.id)));
  }),
];
