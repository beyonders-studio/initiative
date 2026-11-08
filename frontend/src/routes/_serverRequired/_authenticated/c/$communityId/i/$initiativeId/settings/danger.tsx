import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsDangerPage } from "@/pages/initiativeSettings/InitiativeSettingsDangerPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/danger"
)({
  component: InitiativeSettingsDangerPage,
});
