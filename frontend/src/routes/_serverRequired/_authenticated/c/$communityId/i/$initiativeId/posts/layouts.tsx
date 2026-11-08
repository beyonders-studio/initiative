import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SharedLayoutEditorPage } from "@/pages/community/tools/layouts/SharedLayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/posts/layouts"
)({
  component: () => <SharedLayoutEditorPage tool={Tool.post} />,
});
