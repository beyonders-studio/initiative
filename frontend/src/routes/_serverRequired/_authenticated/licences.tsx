import { createFileRoute } from "@tanstack/react-router";

import { LicencesPage } from "@/pages/LicencesPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/licences")({
  component: LicencesPage,
});
