import { createFileRoute } from "@tanstack/react-router";

import { PlacementPage } from "@/pages/operator/PlacementPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/placement")(
  {
    component: PlacementPage,
  }
);
