import { createFileRoute } from "@tanstack/react-router";

import { SettingsEmailPage } from "@/pages/SettingsEmailPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/email")({
  component: SettingsEmailPage,
});
