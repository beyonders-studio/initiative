import { createFileRoute } from "@tanstack/react-router";

import { AnnouncementsPage } from "@/pages/operator/AnnouncementsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/announcements"
)({
  component: AnnouncementsPage,
});
