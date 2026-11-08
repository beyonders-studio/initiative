import { createFileRoute } from "@tanstack/react-router";

import { ResetPasswordPage } from "@/pages/signIn/ResetPasswordPage";

export const Route = createFileRoute("/_serverRequired/reset-password")({
  component: ResetPasswordPage,
});
