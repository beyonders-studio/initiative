import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ItemLayoutEditorPage } from "@/pages/community/tools/layouts/ItemLayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/layouts"
)({
  component: () => <ItemLayoutEditorPage tool={Tool.counter_group} />,
});
