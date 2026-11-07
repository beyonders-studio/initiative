import { createFileRoute } from "@tanstack/react-router";

import { PlatformSettingsLayout } from "@/pages/PlatformSettingsLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform")({
  component: PlatformSettingsLayout,
});
