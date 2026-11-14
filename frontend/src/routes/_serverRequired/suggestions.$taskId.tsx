import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/suggestions/$taskId")({
  component: lazyRouteComponent(() =>
    import("@/pages/site/ideas/IdeaPage").then((m) => ({ default: m.IdeaPage }))
  ),
});
