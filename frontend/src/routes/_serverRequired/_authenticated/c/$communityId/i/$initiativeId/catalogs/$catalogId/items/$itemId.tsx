import { createFileRoute } from "@tanstack/react-router";

import { LazyCatalogDetailPage } from "@/lib/initiativeDetailRoute";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/catalogs/$catalogId/items/$itemId"
)({
  component: LazyCatalogDetailPage,
});
