import { createFileRoute } from "@tanstack/react-router";

import { SettingsLayout } from "@/pages/my/settings/SettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile")({
  component: SettingsLayout,
});
