import { createFileRoute } from "@tanstack/react-router";

import { SettingsLayout } from "@/pages/community/settings/SettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings")({
  component: SettingsLayout,
});
