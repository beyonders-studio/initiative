import { createFileRoute } from "@tanstack/react-router";

import { validateAccessGrantsSearch } from "@/lib/accessGrantsSearch";
import { SettingsAccessGrantsPage } from "@/pages/SettingsAccessGrantsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/access")({
  validateSearch: validateAccessGrantsSearch,
  component: SettingsAccessGrantsPage,
});
