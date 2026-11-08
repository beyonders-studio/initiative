import { createFileRoute } from "@tanstack/react-router";

import { SecurityPage } from "@/pages/platform/security/SecurityPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/security")({
  component: SecurityPage,
});
