import { createFileRoute } from "@tanstack/react-router";

import { EmailPage } from "@/pages/platform/EmailPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/email")({
  component: EmailPage,
});
