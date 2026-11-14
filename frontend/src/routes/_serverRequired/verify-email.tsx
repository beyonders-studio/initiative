import { createFileRoute } from "@tanstack/react-router";

import { VerifyEmailPage } from "@/pages/signIn/VerifyEmailPage";

export const Route = createFileRoute("/_serverRequired/verify-email")({
  component: VerifyEmailPage,
});
