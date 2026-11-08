import { createFileRoute } from "@tanstack/react-router";

import { CommunitySettingsLayout } from "@/pages/CommunitySettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings")({
  component: CommunitySettingsLayout,
});
