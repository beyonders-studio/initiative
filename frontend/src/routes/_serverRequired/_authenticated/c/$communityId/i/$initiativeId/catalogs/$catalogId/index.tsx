import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/catalogs/$catalogId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/catalogs/CatalogDetailPage").then((m) => ({
      default: m.CatalogDetailPage,
    }))
  ),
});
