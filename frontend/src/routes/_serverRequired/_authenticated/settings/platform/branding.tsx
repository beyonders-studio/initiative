import { createFileRoute } from "@tanstack/react-router";

import { SettingsBrandingPage } from "@/pages/SettingsBrandingPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/branding")({
  component: SettingsBrandingPage,
});
