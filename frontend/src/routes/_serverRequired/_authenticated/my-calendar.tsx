import { createFileRoute } from "@tanstack/react-router";

import { CalendarPage } from "@/pages/my/CalendarPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-calendar")({
  component: CalendarPage,
});
