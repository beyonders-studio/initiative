import { format, isValid, parse } from "date-fns";
import { Calendar as CalendarIcon } from "lucide-react";
import * as React from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { parseLocalCalendarDate, resolveLocalDateTime } from "@/lib/localDateTime";
import { dateTimePattern } from "@/lib/timeFormat";
import { cn } from "@/lib/utils";
import { useTimeFormat } from "@/ui/host";

interface DateTimePickerProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  clearLabel?: string;
  calendarProps?: React.ComponentProps<typeof Calendar>;
  includeTime?: boolean;
}

const formatForStorage = (date: Date, includeTime: boolean) =>
  includeTime ? format(date, "yyyy-MM-dd'T'HH:mm") : format(date, "yyyy-MM-dd");

const applyTimeToDate = (date: Date, time: string) =>
  resolveLocalDateTime(format(date, "yyyy-MM-dd"), time, date.toISOString());

// Candidate formats tried (in order) when parsing a manually typed date.
const DATE_FORMATS = [
  "yyyy-MM-dd",
  "MM/dd/yyyy",
  "M/d/yyyy",
  "MM-dd-yyyy",
  "yyyy/MM/dd",
  "MMMM d, yyyy",
  "MMM d, yyyy",
  "MMMM d yyyy",
  "MMM d yyyy",
  "d MMMM yyyy",
  "d MMM yyyy",
];

const DATE_TIME_FORMATS = [
  "yyyy-MM-dd HH:mm",
  "yyyy-MM-dd'T'HH:mm",
  "MM/dd/yyyy HH:mm",
  "M/d/yyyy HH:mm",
  "MM/dd/yyyy h:mm a",
  "M/d/yyyy h:mm a",
  "MMMM d, yyyy h:mm a",
  "MMM d, yyyy h:mm a",
  "MMMM d, yyyy HH:mm",
  "MMM d, yyyy HH:mm",
];

// Parse a free-form typed string into a Date, trying known formats first and
// accepting only complete, round-tripping calendar values. Native parsing
// would silently normalize impossible dates such as February 30.
const parseManualDate = (input: string, includeTime: boolean, reference: Date): Date | null => {
  const trimmed = input.trim();
  if (!trimmed) {
    return null;
  }
  const formats = includeTime ? [...DATE_TIME_FORMATS, ...DATE_FORMATS] : DATE_FORMATS;
  for (const fmt of formats) {
    const parsed = parse(trimmed, fmt, reference);
    // Date-fns rejects invalid days, but local DST gaps can still normalize.
    const normalized = (text: string) =>
      text
        .toLowerCase()
        .replace(/\b0+(\d)/g, "$1")
        .replace(/\s+/g, " ");
    if (isValid(parsed) && normalized(format(parsed, fmt)) === normalized(trimmed)) {
      if (!includeTime) return parsed;
      const time =
        fmt.includes("H") || fmt.includes("h")
          ? format(parsed, "HH:mm")
          : format(reference, "HH:mm");
      return resolveLocalDateTime(format(parsed, "yyyy-MM-dd"), time, reference.toISOString());
    }
  }
  return null;
};

export const DateTimePicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder,
  clearLabel,
  calendarProps,
  includeTime = true,
}: DateTimePickerProps) => {
  const { t } = useTranslation(["dates", "common"]);
  // Read so the typed and trigger labels re-render on a clock change.
  useTimeFormat();
  const parsedValue = value
    ? includeTime
      ? new Date(value)
      : parseLocalCalendarDate(value.slice(0, 10))
    : null;
  const selectedDate = parsedValue && isValid(parsedValue) ? parsedValue : undefined;
  const [invalid, setInvalid] = React.useState(false);
  const errorId = React.useId();
  const timeValue = selectedDate ? format(selectedDate, "HH:mm") : "";
  const defaultPlaceholder = includeTime ? t("picker.pickDateTime") : t("picker.pickDate");

  // Human-friendly representation of the current value for the manual-entry field.
  const displayValue = selectedDate
    ? format(selectedDate, includeTime ? dateTimePattern("MMM d, yyyy") : "MMM d, yyyy")
    : "";
  const [inputValue, setInputValue] = React.useState(displayValue);
  // Keep the text field in sync whenever the committed value changes.
  const [prevDisplayValue, setPrevDisplayValue] = React.useState(displayValue);
  if (prevDisplayValue !== displayValue) {
    setPrevDisplayValue(displayValue);
    setInputValue(displayValue);
    setInvalid(false);
  }

  const [open, setOpen] = React.useState(false);

  // The month the calendar is displaying. Controlled so it follows both the
  // month/year dropdowns and the selected date (e.g. when typed manually).
  const [visibleMonth, setVisibleMonth] = React.useState(() => selectedDate ?? new Date());
  const selectedMonthKey = selectedDate
    ? `${selectedDate.getFullYear()}-${selectedDate.getMonth()}`
    : null;
  // Keyed on the month rather than the date, which is a fresh object each
  // render, so the calendar only jumps when the selected month changes.
  const [prevMonthKey, setPrevMonthKey] = React.useState(selectedMonthKey);
  if (prevMonthKey !== selectedMonthKey) {
    setPrevMonthKey(selectedMonthKey);
    if (selectedDate) {
      setVisibleMonth(selectedDate);
    }
  }

  const mergedCalendarProps = React.useMemo(() => {
    const currentYear = new Date().getFullYear();
    return {
      captionLayout: "dropdown" as const,
      startMonth: new Date(currentYear - 120, 0),
      endMonth: new Date(currentYear + 10, 11),
      ...(calendarProps ?? {}),
    };
  }, [calendarProps]);

  const handleSelectDate = (date: Date | undefined) => {
    if (!date) {
      setInvalid(false);
      setInputValue("");
      onChange("");
      return;
    }
    if (includeTime) {
      const baseTime = selectedDate ? format(selectedDate, "HH:mm") : format(new Date(), "HH:mm");
      const next = applyTimeToDate(date, baseTime);
      if (!next) {
        setInvalid(true);
        return;
      }
      setInvalid(false);
      setInputValue(format(next, dateTimePattern("MMM d, yyyy")));
      onChange(formatForStorage(next, includeTime));
    } else {
      setInvalid(false);
      setInputValue(format(date, "MMM d, yyyy"));
      onChange(formatForStorage(date, includeTime));
    }
  };

  const handleTimeChange = (nextTime: string) => {
    if (!selectedDate) {
      return;
    }
    const next = applyTimeToDate(selectedDate, nextTime);
    if (!next) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setInputValue(format(next, dateTimePattern("MMM d, yyyy")));
    onChange(formatForStorage(next, includeTime));
  };

  // `allowClear` distinguishes an explicit commit (Enter) from an incidental
  // blur. On blur we must NOT emit onChange("") for an empty field: the browser
  // fires blur (mousedown) before a calendar day's click (mouseup), so clearing
  // here would send a spurious "clear" mutation right before the real "set".
  // Clearing is intentional only via Enter or the Clear button.
  const commitInput = (allowClear: boolean) => {
    const trimmed = inputValue.trim();
    setInvalid(false);
    if (!trimmed) {
      if (allowClear) {
        if (value) {
          onChange("");
        }
      } else {
        setInputValue(displayValue);
      }
      return;
    }
    const parsed = parseManualDate(trimmed, includeTime, selectedDate ?? new Date());
    if (!parsed) {
      // Retain the input so the reader can correct it; do not save a different day.
      setInvalid(true);
      return false;
    }
    const next = formatForStorage(parsed, includeTime);
    if (next === value) {
      // No change — just normalize the text to the canonical display.
      setInputValue(displayValue);
    } else {
      onChange(next);
    }
  };

  const handleClear = () => {
    setInvalid(false);
    setInputValue("");
    onChange("");
  };

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setInvalid(false);
      // On open, jump the calendar back to the selected date and reset the text
      // field — closing via Escape unmounts the input without firing onBlur, so
      // any uncommitted text would otherwise linger until the value changes.
      setVisibleMonth(selectedDate ?? new Date());
      setInputValue(displayValue);
    }
    setOpen(next);
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          data-empty={!selectedDate}
          className={cn(
            "inline-flex w-full items-center justify-start gap-2 text-left font-normal data-[empty=true]:text-muted-foreground",
            "min-h-10"
          )}
        >
          <CalendarIcon className="h-4 w-4" />
          {selectedDate ? (
            format(selectedDate, includeTime ? dateTimePattern("PP") : "PP")
          ) : (
            <span>{placeholder ?? defaultPlaceholder}</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <div className="border-b p-3">
          <Input
            id={id ? `${id}-input` : undefined}
            type="text"
            value={inputValue}
            placeholder={t("picker.typeDate")}
            aria-label={t("picker.typeDate")}
            disabled={disabled}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? errorId : undefined}
            onChange={(event) => {
              setInputValue(event.target.value);
              setInvalid(false);
            }}
            onBlur={() => commitInput(false)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (commitInput(true) === false) event.stopPropagation();
              }
            }}
          />
        </div>
        {invalid ? (
          <p id={errorId} role="alert" className="px-3 py-2 text-destructive text-sm">
            {t(includeTime ? "picker.invalidLocalDateTime" : "picker.invalidDate")}
          </p>
        ) : null}
        <Calendar
          {...mergedCalendarProps}
          mode="single"
          selected={selectedDate}
          month={visibleMonth}
          onMonthChange={setVisibleMonth}
          onSelect={handleSelectDate}
          className="w-75 p-3"
        />
        <div className="flex items-end gap-3 border-t bg-muted/30 p-3">
          {includeTime && (
            <div className="flex flex-1 flex-col gap-1">
              <label
                htmlFor={`${id ?? "datetime"}-time`}
                className="font-medium text-muted-foreground text-xs"
              >
                {t("picker.time")}
              </label>
              <Input
                id={`${id ?? "datetime"}-time`}
                type="time"
                aria-invalid={invalid || undefined}
                aria-describedby={invalid ? errorId : undefined}
                step={300}
                value={timeValue}
                onChange={(event) => handleTimeChange(event.target.value)}
                disabled={!selectedDate || disabled}
              />
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-muted-foreground text-xs"
            onClick={handleClear}
            disabled={!selectedDate || disabled}
          >
            {clearLabel ?? t("common:clear")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
