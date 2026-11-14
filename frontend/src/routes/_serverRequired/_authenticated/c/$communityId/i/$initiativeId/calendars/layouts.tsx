import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SharedLayoutEditorPage } from "@/pages/community/tools/layouts/SharedLayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/layouts"
)({
  component: () => <SharedLayoutEditorPage tool={Tool.calendar} />,
});
