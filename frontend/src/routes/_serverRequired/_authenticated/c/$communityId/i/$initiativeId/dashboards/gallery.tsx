import { createFileRoute } from "@tanstack/react-router";

import { WidgetGalleryPage } from "@/pages/initiativeTools/dashboards/WidgetGalleryPage";

// Development surface for the widget harness — see WidgetGalleryPage. Not
// linked from the app; the canvas that will render widgets for real is Phase 2b.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/gallery"
)({
  component: WidgetGalleryPage,
});
