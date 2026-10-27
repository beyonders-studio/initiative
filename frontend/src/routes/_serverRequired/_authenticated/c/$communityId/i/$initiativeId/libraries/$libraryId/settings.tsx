import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsPage } from "@/pages/toolSettings/ToolSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/libraries/$libraryId/settings"
)({
  component: () => <ToolSettingsPage tool={Tool.library} />,
});
