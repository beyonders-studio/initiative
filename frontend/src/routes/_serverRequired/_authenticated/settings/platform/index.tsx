import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformIndexPage } from "@/pages/SettingsPlatformIndexPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/")({
  component: SettingsPlatformIndexPage,
});
