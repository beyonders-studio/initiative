import { createFileRoute } from "@tanstack/react-router";

import { SettingsAuthPage } from "@/pages/SettingsAuthPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/auth")({
  component: SettingsAuthPage,
});
