import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ItemLayoutEditorPage } from "@/pages/initiativeTools/ItemLayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/libraries/$libraryId/layouts"
)({
  component: () => <ItemLayoutEditorPage tool={Tool.library} />,
});
