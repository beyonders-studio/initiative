import { createFileRoute } from "@tanstack/react-router";

import { MyCalendarPage } from "@/pages/user/MyCalendarPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-calendar")({
  component: MyCalendarPage,
});
