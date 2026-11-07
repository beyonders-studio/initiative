import { createFileRoute } from "@tanstack/react-router";

import { UserSettingsLayout } from "@/pages/user/settings/UserSettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile")({
  component: UserSettingsLayout,
});
