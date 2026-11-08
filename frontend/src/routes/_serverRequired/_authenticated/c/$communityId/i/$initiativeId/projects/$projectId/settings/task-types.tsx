import { createFileRoute } from "@tanstack/react-router";

import { TaskTypesPage } from "@/pages/community/tools/projects/settings/taskTypes/TaskTypesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-types"
)({
  component: TaskTypesPage,
});
