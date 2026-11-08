import { createFileRoute } from "@tanstack/react-router";

import { LegalDocumentPage } from "@/pages/LegalDocumentPage";

export const Route = createFileRoute("/_serverRequired/legal/$slug")({
  component: LegalDocumentPage,
});
