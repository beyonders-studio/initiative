import { useTranslation } from "react-i18next";

import { useCalendar, useUpdateCalendar } from "@/hooks/useCalendars";
import { toast } from "@/lib/mascotToast";
import { useToolSettings } from "@/pages/community/tools/settings/ToolSettingsContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { ColorPickerPopover } from "@/ui/color-picker-popover";

/**
 * Calendars' only tool-specific setting, in their settings' Details section:
 * the color their events render in. Persists on pick, the way tags do, so it
 * needs no Save button of its own. A calendar always has a color, so there is
 * nothing to clear.
 */
export const CalendarColorCard = () => {
  const { t } = useTranslation(["calendars", "common"]);
  const { entity } = useToolSettings();
  const calendar = useCalendar(entity.id).data;

  const updateCalendar = useUpdateCalendar(entity.id, {
    onSuccess: () => toast.success(t("common:toolSettings.detailsUpdated")),
  });

  if (!calendar) return null;

  // The pick while it saves; the calendar as read back after.
  const shown = updateCalendar.isPending
    ? (updateCalendar.variables?.color ?? calendar.color)
    : calendar.color;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("calendarColor")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ColorPickerPopover
          id="calendar-color"
          value={shown}
          onChangeComplete={(next) => updateCalendar.mutate({ color: next })}
          disabled={!entity.can.edit}
        />
      </CardContent>
    </Card>
  );
};
