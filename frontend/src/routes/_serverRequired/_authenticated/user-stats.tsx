import { createFileRoute } from "@tanstack/react-router";

import { StatsPage } from "@/pages/my/stats/StatsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/user-stats")({
  component: StatsPage,
});
