import { createFileRoute } from "@tanstack/react-router";

import { ForgotPasswordPage } from "@/pages/signIn/ForgotPasswordPage";

export const Route = createFileRoute("/_serverRequired/forgot-password")({
  component: ForgotPasswordPage,
});
