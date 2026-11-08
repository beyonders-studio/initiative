import { useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  RecurrencePreviewRequest,
  RecurrenceStrategy,
} from "@/api/generated/initiativeAPI.schemas";
import { useRecurrencePreview } from "@/hooks/useRecurrencePreview";
import { formatDate, formatDateTime } from "@/lib/formatDate";
import {
  createRecurrenceFromPreset,
  detectRecurrencePreset,
  getReferenceDate,
  isHourlyRule,
  isValidTaskRecurrence,
  type MonthlyMode,
  maxOccurrences,
  type RecurrenceFrequency,
  type RecurrencePreset,
  type RecurrenceRule,
  type RecurrenceWeekday,
  sortMonthDays,
  summarizeRecurrence,
  type TaskRecurrenceValue,
  type TaskWeekPosition,
  toRRule,
  WEEKDAYS,
  withFrequency,
  withMonthlyMode,
} from "@/lib/recurrence";
import { browserTimezone } from "@/lib/timezones";
import type { TranslateFn } from "@/types/i18n";
import { DateTimePicker } from "@/ui/date-time-picker";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { dateTimeFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const hourlyQuickOption = (
  kind: "task" | "event",
  enabled: boolean,
  label: string
): { value: "hourly"; label: string }[] =>
  kind === "task" && enabled ? [{ value: "hourly", label }] : [];

const POSITION_KEYS: Record<TaskWeekPosition, string> = {
  first: "recurrence.positionFirst",
  second: "recurrence.positionSecond",
  third: "recurrence.positionThird",
  fourth: "recurrence.positionFourth",
  fifth: "recurrence.positionFifth",
  last: "recurrence.positionLast",
};
const MODES: MonthlyMode[] = ["day_of_month", "weekday", "weekdays", "set"];
const MONTH_DAYS = [...Array.from({ length: 31 }, (_, i) => i + 1), -1];
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);
const UNIT_KEYS: Record<RecurrenceFrequency, string> = {
  hourly: "recurrence.repeatEveryHours",
  daily: "recurrence.repeatEveryDays",
  weekly: "recurrence.repeatEveryWeeks",
  monthly: "recurrence.repeatEveryMonths",
  yearly: "recurrence.repeatEveryYears",
};

type RecurrenceEditorProps = {
  /** `"custom"` is a stored rule the editor can't show, kept until replaced. */
  value: RecurrenceRule | "custom" | null;
  onChange: (rule: RecurrenceRule | null) => void;
  kind: "task" | "event";
  /** The series start: an event's start, a task's due date. */
  referenceDate?: string | null;
  /** An all-day event, whose days are UTC dates. */
  allDay?: boolean;
  /** The stored rule and its shift, previewed while it is kept as custom. */
  stored?: { rule: string; shift: number } | null;
  /** Tasks only: whether the next one follows the schedule or completion. */
  strategy?: RecurrenceStrategy;
  onStrategyChange?: (value: RecurrenceStrategy) => void;
  limit?: number | null;
  hasDueDate?: boolean;
  /** Tasks update rule, strategy and daily maximum in one edit. */
  onTaskChange?: (value: TaskRecurrenceValue) => void;
  disabled?: boolean;
};

/** A row of toggles, at least one of which stays on. */
const Chips = <T extends string | number>({
  options,
  selected,
  label,
  onChange,
  disabled,
}: {
  options: T[];
  selected: T[];
  label: (value: T) => string;
  onChange: (next: T[]) => void;
  disabled?: boolean;
}) => (
  <div className="flex flex-wrap gap-2">
    {options.map((option) => {
      const on = selected.includes(option);
      return (
        <button
          key={option}
          type="button"
          aria-pressed={on}
          disabled={disabled}
          onClick={() => {
            const next = on ? selected.filter((value) => value !== option) : [...selected, option];
            if (next.length) onChange(next);
          }}
          className={cn(
            "min-w-9 rounded-md border px-2 py-1 text-sm",
            on ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground",
            disabled ? "opacity-70" : ""
          )}
        >
          {label(option)}
        </button>
      );
    })}
  </div>
);

/**
 * The one repeat editor, for tasks and events: quick picks, and a custom
 * builder for every shape the calendar repeats on, with the next dates from
 * the server underneath so the form never shows a date the calendar won't.
 */
export const RecurrenceEditor = ({
  value,
  onChange: setRule,
  kind,
  referenceDate,
  allDay = false,
  stored,
  strategy,
  onStrategyChange,
  limit = null,
  hasDueDate = true,
  onTaskChange,
  disabled = false,
}: RecurrenceEditorProps) => {
  const { t, i18n } = useTranslation(["projects", "dates"]);
  const controlId = useId();
  const rule = value === "custom" ? null : value;
  const hourly = kind === "task" && strategy === "rolling" && isHourlyRule(value);
  const limitInvalid = hourly && !isValidTaskRecurrence({ rule: value, strategy, limit });
  const changeStrategy = (next: RecurrenceStrategy) => {
    if (onTaskChange) {
      const nextRule =
        next === "fixed" && isHourlyRule(value)
          ? rule
            ? withFrequency(rule, "daily", referenceDate)
            : null
          : value;
      onTaskChange({
        rule: nextRule,
        strategy: next,
        limit: next === "rolling" && isHourlyRule(nextRule) ? limit : null,
      });
    } else onStrategyChange?.(next);
  };
  const detected = value === "custom" ? "custom" : detectRecurrencePreset(rule);
  // A quick pick the rule happens to match stays in the builder once opened.
  const [building, setBuilding] = useState(detected === "custom" && rule !== null);
  useEffect(() => {
    if (rule === null) setBuilding(false);
    else if (detected === "custom") setBuilding(true);
  }, [detected, rule]);
  const preset = building ? "custom" : detected;
  const anchor = getReferenceDate(referenceDate);
  // A count stays within what the rule's frequency and interval allow.
  const onChange = (next: RecurrenceRule | null) => {
    const nextRule = next?.end_after_occurrences
      ? {
          ...next,
          end_after_occurrences: Math.min(next.end_after_occurrences, maxOccurrences(next)),
        }
      : next;
    if (onTaskChange)
      onTaskChange({
        rule: nextRule,
        strategy: !nextRule ? "fixed" : isHourlyRule(nextRule) ? "rolling" : (strategy ?? "fixed"),
        limit: isHourlyRule(nextRule) && strategy === "rolling" ? limit : null,
      });
    else setRule(nextRule);
  };

  const choosePreset = (next: RecurrencePreset) => {
    if (next === "custom") {
      setBuilding(true);
      onChange(rule ?? createRecurrenceFromPreset("daily", referenceDate));
      return;
    }
    setBuilding(next === "hourly");
    onChange(createRecurrenceFromPreset(next, referenceDate));
  };

  const quickOptions = useMemo(
    (): { value: RecurrencePreset; label: string }[] => [
      { value: "none", label: t("recurrence.doesNotRepeat") },
      { value: "daily", label: t("recurrence.daily") },
      ...hourlyQuickOption(kind, Boolean(onTaskChange), t("recurrence.hourlyAfterCompletion")),
      { value: "weekdays", label: t("recurrence.everyWeekday") },
      {
        value: "weekly",
        label: t("recurrence.weeklyOn", {
          day: dateTimeFormat(i18n.language, { weekday: "long" }).format(anchor),
        }),
      },
      { value: "monthly", label: t("recurrence.monthlyOnDay", { day: anchor.getDate() }) },
      {
        value: "yearly",
        label: t("recurrence.annuallyOn", {
          month: dateTimeFormat(i18n.language, { month: "long" }).format(anchor),
          day: anchor.getDate(),
        }),
      },
      { value: "custom", label: t("recurrence.custom") },
    ],
    [anchor, i18n.language, kind, onTaskChange, t]
  );

  const monthName = (month: number) =>
    dateTimeFormat(i18n.language, { month: "short" }).format(new Date(2026, month - 1, 1));
  const weekdayName = (day: RecurrenceWeekday) => t(`dates:weekdaysShort.${day}` as never);

  // The next dates, from the rule as it would be saved, or the stored one.
  const previewing = strategy !== "rolling" && referenceDate;
  const start =
    allDay && referenceDate
      ? `${anchor.getFullYear()}-${String(anchor.getMonth() + 1).padStart(2, "0")}-${String(anchor.getDate()).padStart(2, "0")}T00:00:00Z`
      : referenceDate;
  const request: RecurrencePreviewRequest | null =
    !previewing || !start
      ? null
      : rule
        ? {
            rule: toRRule(rule, { allDay }),
            start,
            tz: allDay ? undefined : browserTimezone(),
            kind,
          }
        : value === "custom" && stored
          ? { rule: stored.rule, start, shift: stored.shift, kind }
          : null;
  const preview = useRecurrencePreview(request);
  const dates = request && !preview.isError ? (preview.data?.occurrences ?? []) : [];
  // Dates for an earlier pick, shown faded until the current one's arrive.
  const stale = preview.isPlaceholderData || preview.isFetching || !preview.settled;

  const summary = limitInvalid
    ? null
    : value === "custom"
      ? t("dates:recurrenceSummary.custom")
      : rule
        ? summarizeRecurrence(rule, { referenceDate, strategy, limit }, t as TranslateFn)
        : null;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${controlId}-preset`}>{t("recurrence.repeat")}</Label>
        <Select
          value={preset}
          onValueChange={(next) => {
            const option = quickOptions.find((option) => option.value === next);
            if (option) choosePreset(option.value);
          }}
          disabled={disabled}
        >
          <SelectTrigger id={`${controlId}-preset`}>
            <SelectValue placeholder={t("recurrence.doesNotRepeat")} />
          </SelectTrigger>
          <SelectContent>
            {quickOptions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {summary ? <p className="text-muted-foreground text-sm">{summary}</p> : null}
        {dates.length ? (
          <div
            className={cn("text-muted-foreground text-xs", stale && "opacity-50")}
            aria-busy={stale}
          >
            <span className="font-medium">{t("recurrence.nextDates")}</span>{" "}
            {dates
              .map((date) => (allDay ? formatDate(date.slice(0, 10)) : formatDateTime(date)))
              .join(" · ")}
          </div>
        ) : null}
      </div>

      {building && rule ? (
        <div className="space-y-4 rounded-md border border-border/70 p-4">
          <div className="grid grid-cols-pair gap-3">
            <Field label={t("recurrence.frequency")}>
              <Select
                value={rule.frequency}
                onValueChange={(next) =>
                  onChange(withFrequency(rule, next as RecurrenceFrequency, referenceDate))
                }
                disabled={disabled}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {kind === "task" && strategy === "rolling" && onTaskChange ? (
                    <SelectItem value="hourly">{t("recurrence.frequencyHourly")}</SelectItem>
                  ) : null}
                  <SelectItem value="daily">{t("recurrence.frequencyDaily")}</SelectItem>
                  <SelectItem value="weekly">{t("recurrence.frequencyWeekly")}</SelectItem>
                  <SelectItem value="monthly">{t("recurrence.frequencyMonthly")}</SelectItem>
                  <SelectItem value="yearly">{t("recurrence.frequencyYearly")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label={t("recurrence.repeatEvery")} hint={t(UNIT_KEYS[rule.frequency] as never)}>
              <Input
                type="number"
                min={1}
                max={366}
                value={rule.interval}
                onChange={(event) => {
                  const parsed = Number.parseInt(event.target.value, 10);
                  onChange({
                    ...rule,
                    interval: Number.isNaN(parsed) ? 1 : Math.max(1, Math.min(366, parsed)),
                  });
                }}
                disabled={disabled}
              />
            </Field>
          </div>

          {rule.frequency === "weekly" ? (
            <div className="space-y-2">
              <Label>{t("recurrence.repeatOn")}</Label>
              <Chips
                options={WEEKDAYS.map((day) => day.value)}
                selected={rule.weekdays}
                label={weekdayName}
                onChange={(weekdays) => onChange({ ...rule, weekdays })}
                disabled={disabled}
              />
            </div>
          ) : null}

          {rule.frequency === "yearly" ? (
            <div className="space-y-2">
              <Label>{t("recurrence.months")}</Label>
              <Chips
                options={MONTHS}
                selected={rule.months.length ? rule.months : [anchor.getMonth() + 1]}
                label={monthName}
                onChange={(months) => onChange({ ...rule, months })}
                disabled={disabled}
              />
            </div>
          ) : null}

          {rule.frequency === "monthly" || rule.frequency === "yearly" ? (
            <div className="space-y-2">
              <Label>{t("recurrence.on")}</Label>
              <Select
                value={rule.monthly_mode}
                onValueChange={(mode) =>
                  onChange(withMonthlyMode(rule, mode as MonthlyMode, referenceDate))
                }
                disabled={disabled}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* The first or last is taken once per repeat, so a year's
                      would be one date a year, not one a month. */}
                  {MODES.filter((mode) => mode !== "set" || rule.frequency === "monthly").map(
                    (mode) => (
                      <SelectItem key={mode} value={mode}>
                        {t(`recurrence.mode.${mode}` as never)}
                      </SelectItem>
                    )
                  )}
                </SelectContent>
              </Select>

              {rule.monthly_mode === "day_of_month" ? (
                <Chips
                  options={MONTH_DAYS}
                  selected={rule.month_days}
                  label={(day) => (day === -1 ? t("recurrence.lastDay") : String(day))}
                  onChange={(days) => onChange({ ...rule, month_days: sortMonthDays(days) })}
                  disabled={disabled}
                />
              ) : null}

              {rule.monthly_mode === "weekday" ? (
                <div className="grid grid-cols-pair gap-3">
                  <Select
                    value={rule.weekday_position ?? "first"}
                    onValueChange={(position) =>
                      onChange({ ...rule, weekday_position: position as TaskWeekPosition })
                    }
                    disabled={disabled}
                  >
                    <SelectTrigger aria-label={t("recurrence.position")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(POSITION_KEYS).map(([position, key]) => (
                        <SelectItem key={position} value={position}>
                          {t(key as never)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select
                    value={rule.weekday ?? "monday"}
                    onValueChange={(weekday) =>
                      onChange({ ...rule, weekday: weekday as RecurrenceWeekday })
                    }
                    disabled={disabled}
                  >
                    <SelectTrigger aria-label={t("recurrence.weekday")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {WEEKDAYS.map((weekday) => (
                        <SelectItem key={weekday.value} value={weekday.value}>
                          {t(`dates:weekdays.${weekday.value}` as never)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : null}

              {rule.monthly_mode === "set" ? (
                <Select
                  value={rule.set_position}
                  onValueChange={(position) =>
                    onChange({ ...rule, set_position: position as "first" | "last" })
                  }
                  disabled={disabled}
                >
                  <SelectTrigger aria-label={t("recurrence.position")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="first">{t("recurrence.positionFirst")}</SelectItem>
                    <SelectItem value="last">{t("recurrence.positionLast")}</SelectItem>
                  </SelectContent>
                </Select>
              ) : null}

              {rule.monthly_mode === "weekdays" || rule.monthly_mode === "set" ? (
                <Chips
                  options={WEEKDAYS.map((day) => day.value)}
                  selected={rule.weekdays}
                  label={weekdayName}
                  onChange={(weekdays) => onChange({ ...rule, weekdays })}
                  disabled={disabled}
                />
              ) : null}
            </div>
          ) : null}

          <div className="space-y-2">
            <Label>{t("recurrence.ends")}</Label>
            <Select
              value={rule.ends}
              onValueChange={(ends) =>
                onChange({
                  ...rule,
                  ends: ends as RecurrenceRule["ends"],
                  end_date: ends === "on_date" ? (rule.end_date ?? anchor.toISOString()) : null,
                  end_after_occurrences:
                    ends === "after_occurrences" ? (rule.end_after_occurrences ?? 5) : null,
                })
              }
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="never">{t("recurrence.endsNever")}</SelectItem>
                <SelectItem value="on_date">{t("recurrence.endsOnDate")}</SelectItem>
                <SelectItem value="after_occurrences">{t("recurrence.endsAfterCount")}</SelectItem>
              </SelectContent>
            </Select>
            {rule.ends === "on_date" ? (
              <DateTimePicker
                value={rule.end_date ? rule.end_date.slice(0, 10) : ""}
                onChange={(end) => onChange({ ...rule, end_date: end || null })}
                disabled={disabled}
                includeTime={false}
              />
            ) : null}
            {rule.ends === "after_occurrences" ? (
              <Input
                type="number"
                min={1}
                max={maxOccurrences(rule)}
                value={rule.end_after_occurrences ?? 5}
                onChange={(event) =>
                  onChange({
                    ...rule,
                    end_after_occurrences: Math.max(
                      1,
                      Math.min(maxOccurrences(rule), Number(event.target.value) || 1)
                    ),
                  })
                }
                disabled={disabled}
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {hourly ? (
        <Field
          label={t("recurrence.dailyLimit")}
          hint={t("recurrence.hourlyCompletionHelp")}
          error={
            (!hasDueDate || limitInvalid) &&
            t(!hasDueDate ? "recurrence.hourlyNeedsDueDate" : "recurrence.limitInvalid")
          }
        >
          <Input
            name="recurrence_limit"
            type="number"
            min={1}
            max={24}
            step={1}
            value={limit === null || Number.isNaN(limit) ? "" : limit}
            placeholder={t("recurrence.unlimited")}
            ref={(input) =>
              input?.setCustomValidity(
                limitInvalid
                  ? t("recurrence.limitInvalid")
                  : !hasDueDate
                    ? t("recurrence.hourlyNeedsDueDate")
                    : ""
              )
            }
            onChange={(event) =>
              onTaskChange?.({
                rule: value,
                strategy: "rolling",
                limit: event.target.value === "" ? null : event.target.valueAsNumber,
              })
            }
            disabled={disabled}
          />
        </Field>
      ) : null}

      {kind === "task" && rule && strategy && (onStrategyChange || onTaskChange) ? (
        <div className="space-y-2">
          <Label htmlFor={`${controlId}-strategy`}>{t("recurrence.repeatStrategy")}</Label>
          <Select
            value={strategy}
            onValueChange={(next) => {
              if (next === "fixed" || next === "rolling") changeStrategy(next);
            }}
            disabled={disabled}
          >
            <SelectTrigger id={`${controlId}-strategy`}>
              <SelectValue placeholder={t("recurrence.selectStrategy")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fixed">{t("recurrence.strategyOnSchedule")}</SelectItem>
              <SelectItem value="rolling">{t("recurrence.strategyAfterCompletion")}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            {strategy === "rolling"
              ? t("recurrence.strategyAfterCompletionDescription")
              : t("recurrence.strategyOnScheduleDescription")}
          </p>
        </div>
      ) : null}
    </div>
  );
};
