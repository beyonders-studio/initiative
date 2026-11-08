import { createFileRoute } from "@tanstack/react-router";

import { SettingsLayout } from "@/pages/platform/SettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform")({
  component: SettingsLayout,
});
