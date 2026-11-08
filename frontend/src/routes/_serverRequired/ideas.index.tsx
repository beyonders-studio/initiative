import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/ideas/")({
  component: lazyRouteComponent(() =>
    import("@/pages/IdeasPage").then((m) => ({ default: m.IdeasPage }))
  ),
});
