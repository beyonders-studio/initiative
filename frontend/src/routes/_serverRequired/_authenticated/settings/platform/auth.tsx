import { createFileRoute } from "@tanstack/react-router";

import { AuthPage } from "@/pages/platform/auth/AuthPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/auth")({
  component: AuthPage,
});
