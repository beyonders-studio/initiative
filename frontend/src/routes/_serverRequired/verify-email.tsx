import { createFileRoute } from "@tanstack/react-router";

import { VerifyEmailPage } from "@/pages/VerifyEmailPage";

export const Route = createFileRoute("/_serverRequired/verify-email")({
  component: VerifyEmailPage,
});
