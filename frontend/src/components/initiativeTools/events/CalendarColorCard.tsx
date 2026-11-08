import { useTranslation } from "react-i18next";

import { useUpdateCalendar } from "@/hooks/useCalendars";
import { toast } from "@/lib/mascotToast";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { ColorPickerPopover } from "@/ui/color-picker-popover";

type CalendarColorCardProps = {
  calendarId: number;
  color: string;
  disabled?: boolean;
};

/**
 * Calendars' only tool-specific setting: the color their events render in.
 * Persists on pick, the way tags do, so it needs no Save button of its own.
 * A calendar always has a color, so there is nothing to clear.
 */
export const CalendarColorCard = ({ calendarId, color, disabled }: CalendarColorCardProps) => {
  const { t } = useTranslation(["calendars", "common"]);

  const updateCalendar = useUpdateCalendar(calendarId, {
    onSuccess: () => toast.success(t("common:toolSettings.detailsUpdated")),
  });
  // The pick while it saves; the calendar as read back after.
  const shown = updateCalendar.isPending ? (updateCalendar.variables?.color ?? color) : color;

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
          disabled={disabled}
        />
      </CardContent>
    </Card>
  );
};
