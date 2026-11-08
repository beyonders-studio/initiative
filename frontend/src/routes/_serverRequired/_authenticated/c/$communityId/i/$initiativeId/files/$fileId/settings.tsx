import { createFileRoute } from "@tanstack/react-router";

import { FileSettingsPage } from "@/pages/initiativeTools/files/FileSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/$fileId/settings"
)({
  component: FileSettingsPage,
});
