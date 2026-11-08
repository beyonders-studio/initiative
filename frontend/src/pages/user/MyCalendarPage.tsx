import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { invalidate, q } from "@/api/query-keys";
import { MyCalendar } from "@/components/calendar/MyCalendar";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { PullToRefresh } from "@/ui/pull-to-refresh";

export const MyCalendarPage = () => {
  const { t } = useTranslation("tasks");

  const handleRefresh = useCallback(async () => {
    await invalidate(q.allTasks(), q.allCalendars());
  }, []);

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <MyCalendar
        frame={({ filters, body }) => (
          <div className="space-y-6">
            <h1 className="font-semibold text-3xl tracking-tight">{t("myCalendar.title")}</h1>
            <ToolListToolbar filters={filters} />
            {body}
          </div>
        )}
      />
    </PullToRefresh>
  );
};
