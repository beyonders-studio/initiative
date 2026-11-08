import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { DateTimePicker } from "@/ui/date-time-picker";
import { Label } from "@/ui/label";
import { formatClockSlot } from "@/ui/lib/timeFormat";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

import {
  composeDateTime,
  datesAreValid,
  endTimeOptionsFor,
  parseLocalDate,
  reconcileEndTime,
  shiftEndPreservingDuration,
  TIME_OPTIONS,
} from "./eventDateTime";

/** An event's start and end as the form holds them: `yyyy-MM-dd` dates and
 * `HH:MM` values, with original instants retained for precise unchanged fields. */
export interface EventTiming {
  allDay: boolean;
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
  startInstant?: string;
  endInstant?: string;
}

/**
 * The range the form's timing describes, as the `start_at`/`end_at` an event is
 * saved with — or null while the end falls before the start. An all-day event
 * runs from the start day's midnight to the end of its last day.
 */
export function eventRange(timing: EventTiming): { start_at: string; end_at: string } | null {
  const { allDay, startDate, startTime, endDate, endTime, startInstant, endInstant } = timing;
  if (!datesAreValid(allDay, startDate, startTime, endDate, endTime, startInstant, endInstant))
    return null;
  const lastDate = endDate || startDate;
  const start = allDay
    ? new Date(`${startDate}T00:00:00Z`)
    : composeDateTime(startDate, startTime, startInstant);
  const end = allDay
    ? new Date(`${lastDate}T23:59:59Z`)
    : composeDateTime(lastDate, endTime, endInstant);
  return start && end ? { start_at: start.toISOString(), end_at: end.toISOString() } : null;
}

const TimeSelect = ({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string }[];
  onChange: (value: string) => void;
}) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger>
      <SelectValue />
    </SelectTrigger>
    <SelectContent className="max-h-60">
      {[
        ...options,
        ...(value && !options.some((option) => option.value === value) ? [{ value }] : []),
      ]
        .sort((a, b) => a.value.localeCompare(b.value))
        .map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {formatClockSlot(opt.value)}
          </SelectItem>
        ))}
    </SelectContent>
  </Select>
);

/**
 * The all-day switch and the start/end pickers of an event. Moving the start
 * moves the end with it, so the event keeps its length (a 90-minute event stays
 * 90 minutes; a multi-day event keeps its span, and the end may land on a later
 * day — that's how multi-day timed events are made).
 */
export const EventDateTimeFields = ({
  value,
  onChange,
}: {
  value: EventTiming;
  onChange: (patch: Partial<EventTiming>) => void;
}) => {
  const { t } = useTranslation(["calendars", "common", "dates"]);
  const allDayId = useId();
  const { allDay, startDate, startTime, endDate, endTime } = value;

  const endTimeOptions = useMemo(
    () => endTimeOptionsFor(startDate, endDate, startTime),
    [startDate, endDate, startTime]
  );
  const minEndDate = parseLocalDate(startDate);
  const endCalendarProps = minEndDate ? { disabled: { before: minEndDate } } : undefined;

  const applyStart = (nextDate: string, nextTime: string) =>
    onChange({
      startDate: nextDate,
      startTime: nextTime,
      ...shiftEndPreservingDuration(
        startDate,
        startTime,
        endDate,
        endTime,
        nextDate,
        nextTime,
        value.startInstant,
        value.endInstant
      ),
    });

  const startDateField = (
    <div className="space-y-2">
      <Label>{t("startDate")}</Label>
      <DateTimePicker
        value={startDate}
        includeTime={false}
        onChange={(next) =>
          allDay
            ? onChange({ startDate: next, endDate: !endDate || next > endDate ? next : endDate })
            : applyStart(next, startTime)
        }
      />
    </div>
  );

  return (
    <>
      <div className="flex items-center gap-3">
        <Switch
          id={allDayId}
          checked={allDay}
          onCheckedChange={(next) => onChange({ allDay: next })}
        />
        <Label htmlFor={allDayId}>{t("common:calendar.allDay")}</Label>
      </div>

      {!allDay && !eventRange(value) && startDate && endDate ? (
        <p role="alert" className="text-destructive text-sm">
          {composeDateTime(startDate, startTime, value.startInstant) &&
          composeDateTime(endDate, endTime, value.endInstant)
            ? t("dates:picker.invalidEventRange")
            : t("dates:picker.invalidLocalDateTime")}
        </p>
      ) : null}
      {allDay ? (
        <div className="grid grid-cols-2 gap-4">
          {startDateField}
          <div className="space-y-2">
            <Label>{t("endDate")}</Label>
            <DateTimePicker
              value={endDate}
              includeTime={false}
              onChange={(next) => onChange({ endDate: next })}
              calendarProps={endCalendarProps}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            {startDateField}
            <div className="space-y-2">
              <Label>{t("startTime")}</Label>
              <TimeSelect
                value={startTime}
                options={TIME_OPTIONS}
                onChange={(next) => applyStart(startDate, next)}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>{t("endDate")}</Label>
              <DateTimePicker
                value={endDate}
                includeTime={false}
                onChange={(next) =>
                  onChange({
                    endDate: next,
                    endTime: reconcileEndTime(startDate, startTime, next, endTime),
                  })
                }
                calendarProps={endCalendarProps}
              />
            </div>
            <div className="space-y-2">
              <Label>{t("endTime")}</Label>
              <TimeSelect
                value={endTime}
                options={endTimeOptions}
                onChange={(next) => onChange({ endTime: next })}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
};
