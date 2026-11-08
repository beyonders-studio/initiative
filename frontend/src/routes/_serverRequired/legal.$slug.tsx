import { createFileRoute } from "@tanstack/react-router";

import { LegalPage } from "@/pages/site/LegalPage";

export const Route = createFileRoute("/_serverRequired/legal/$slug")({
  component: LegalPage,
});
