import { createFileRoute } from "@tanstack/react-router";

import { ShareRequestsPage } from "@/pages/ShareRequestsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/share-requests_/$batchId"
)({
  component: ShareRequestsPage,
});
