import { createFileRoute } from "@tanstack/react-router";

import { PrivacyPage } from "@/pages/my/settings/privacy/PrivacyPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/privacy")({
  component: PrivacyPage,
});
