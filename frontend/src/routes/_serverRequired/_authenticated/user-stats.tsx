import { createFileRoute } from "@tanstack/react-router";

import { MyStatsPage } from "@/pages/user/MyStatsPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/user-stats")({
  component: MyStatsPage,
});
