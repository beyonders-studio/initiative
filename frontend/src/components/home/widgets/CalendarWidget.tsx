/**
 * My Calendar on the home page: the same calendar, filters and view as the
 * page, in a card whose title opens the page.
 */

import { CalendarDays } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MyCalendar } from "@/components/calendar/MyCalendar";
import { HomeWidgetCard } from "@/components/home/HomeWidgetCard";
import { ToolFilterButton } from "@/components/tools/ToolFilterPanel";

export const CalendarWidget = () => {
  const { t } = useTranslation("home");
  return (
    <MyCalendar
      framed={false}
      frame={({ filters, body }) => (
        <HomeWidgetCard
          icon={CalendarDays}
          title={t("widgets.calendar.title")}
          to="/my-calendar"
          actions={<ToolFilterButton {...filters} />}
        >
          {body}
        </HomeWidgetCard>
      )}
    />
  );
};
