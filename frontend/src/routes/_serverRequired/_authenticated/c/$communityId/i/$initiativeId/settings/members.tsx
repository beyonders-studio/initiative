import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsMembersPage } from "@/pages/initiativeSettings/InitiativeSettingsMembersPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/members"
)({
  component: InitiativeSettingsMembersPage,
});
