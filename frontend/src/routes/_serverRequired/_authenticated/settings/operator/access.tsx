import { createFileRoute } from "@tanstack/react-router";

import { validateAccessGrantsSearch } from "@/lib/accessGrantsSearch";
import { AccessPage } from "@/pages/operator/access/AccessPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/access")({
  validateSearch: validateAccessGrantsSearch,
  component: AccessPage,
});
