import { createFileRoute } from "@tanstack/react-router";

import { SettingsStoragePage } from "@/pages/SettingsStoragePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/storage")({
  component: SettingsStoragePage,
});
