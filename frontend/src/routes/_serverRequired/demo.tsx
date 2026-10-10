import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/demo")({
  component: lazyRouteComponent(() =>
    import("@/pages/DemoPage").then((m) => ({ default: m.DemoPage }))
  ),
});
