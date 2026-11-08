import { createFileRoute } from "@tanstack/react-router";

import { TaskStatusesPage } from "@/pages/community/tools/projects/settings/TaskStatusesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-statuses"
)({
  component: TaskStatusesPage,
});
