import { createFileRoute } from "@tanstack/react-router";

import { SettingsIntakePage } from "@/pages/SettingsIntakePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/intake")({
  component: SettingsIntakePage,
});
