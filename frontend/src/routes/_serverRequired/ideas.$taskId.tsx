import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/ideas/$taskId")({
  component: lazyRouteComponent(() =>
    import("@/pages/IdeaPage").then((m) => ({ default: m.IdeaPage }))
  ),
});
