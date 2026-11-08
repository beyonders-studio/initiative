import { createFileRoute } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings"
)({
  component: () => <SettingsLayout tool={Tool.counter_group} />,
});
