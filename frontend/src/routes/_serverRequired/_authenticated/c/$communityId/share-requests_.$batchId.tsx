import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/share-requests_/$batchId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/ShareRequestsPage").then((m) => ({ default: m.ShareRequestsPage }))
  ),
});
