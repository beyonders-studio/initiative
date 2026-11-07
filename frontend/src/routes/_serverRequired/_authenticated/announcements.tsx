import { createFileRoute } from "@tanstack/react-router";

import { AnnouncementsArchivePage } from "@/pages/AnnouncementsArchivePage";

export const Route = createFileRoute("/_serverRequired/_authenticated/announcements")({
  component: AnnouncementsArchivePage,
});
