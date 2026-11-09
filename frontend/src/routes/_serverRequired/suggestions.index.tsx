import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/suggestions/")({
  component: lazyRouteComponent(() =>
    import("@/pages/site/ideas/IdeasPage").then((m) => ({ default: m.IdeasPage }))
  ),
});
