import { createFileRoute } from "@tanstack/react-router";

import { SettingsPushPage } from "@/pages/SettingsPushPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/push")({
  component: SettingsPushPage,
});
