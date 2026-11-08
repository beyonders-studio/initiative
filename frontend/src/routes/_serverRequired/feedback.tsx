import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { leaveForSignIn, NotInApp } from "@/lib/webOnlyRoute";

export const Route = createFileRoute("/_serverRequired/feedback")({
  beforeLoad: leaveForSignIn,
  // Decided at build time, so an app package carries no copy of the page.
  component: __IS_CAPACITOR__
    ? NotInApp
    : lazyRouteComponent(() =>
        import("@/pages/FeedbackPage").then((m) => ({ default: m.FeedbackPage }))
      ),
});
