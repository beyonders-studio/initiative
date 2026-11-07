import { createFileRoute } from "@tanstack/react-router";

import { OidcCallbackPage } from "@/pages/OidcCallbackPage";

export const Route = createFileRoute("/_serverRequired/oidc/callback")({
  component: OidcCallbackPage,
});
