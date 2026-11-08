import { createFileRoute } from "@tanstack/react-router";

import { SecurityPage } from "@/pages/my/settings/security/SecurityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/security")({
  component: SecurityPage,
});
