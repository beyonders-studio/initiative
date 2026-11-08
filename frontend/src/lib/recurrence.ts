import type { RecurrenceStrategy } from "@/api/generated/initiativeAPI.schemas";
import { browserTimezone } from "@/lib/timezones";
import type { TranslateFn } from "@/types/i18n";
import { dateTimeFormat, listFormat } from "@/ui/lib/intl";

/** The task's rule, completion strategy and optional daily maximum change together. */
export type TaskRecurrenceValue = {
  rule: RecurrenceRule | "custom" | null;
  strategy: RecurrenceStrategy;
  limit: number | null;
};

export const isHourlyRule = (rule: RecurrenceRule | "custom" | null): boolean =>
  rule !== null && rule !== "custom" && rule.frequency === "hourly";

export const isValidTaskRecurrence = (value: TaskRecurrenceValue): boolean => {
  const hourly = isHourlyRule(value.rule);
  if (hourly && value.strategy !== "rolling") return false;
  if (value.limit === null) return true;
  return (
    hourly &&
    value.strategy === "rolling" &&
    Number.isInteger(value.limit) &&
    value.limit >= 1 &&
    value.limit <= 24
  );
};

export type TaskWeekPosition = "first" | "second" | "third" | "fourth" | "fifth" | "last";
export type RecurrenceFrequency = "hourly" | "daily" | "weekly" | "monthly" | "yearly";
export type RecurrenceWeekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

/**
 * How a monthly or yearly repeat picks its days: by their numbers, the nth of
 * a weekday, every one of some weekdays, or the first or last of them (the
 * last work day is the last of Monday to Friday).
 */
export type MonthlyMode = "day_of_month" | "weekday" | "weekdays" | "set";

/**
 * A repeat as the form edits it: its days as picked, in the viewer's zone.
 * It goes out through {@link toRRule} with the browser's zone, which the
 * server keeps as a shift beside the rule, and comes back through
 * {@link fromStored}.
 */
export type RecurrenceRule = {
  frequency: RecurrenceFrequency;
  interval: number;
  /** Weekly, the days; monthly or yearly, the days `weekdays` and `set` pick from. */
  weekdays: RecurrenceWeekday[];
  monthly_mode: MonthlyMode;
  /** Days of the month, -1 for the last. One day past 28 on its own falls on a
   *  short month's last day. */
  month_days: number[];
  /** Yearly, the months (1–12); none repeats in the start's month. */
  months: number[];
  weekday_position: TaskWeekPosition | null;
  weekday: RecurrenceWeekday | null;
  set_position: "first" | "last";
  ends: "never" | "on_date" | "after_occurrences";
  end_after_occurrences: number | null;
  end_date: string | null;
};

export type RecurrencePreset =
  | "none"
  | "hourly"
  | "daily"
  | "weekly"
  | "weekdays"
  | "monthly"
  | "yearly"
  | "custom";

type WeekdayConfig = {
  value: RecurrenceWeekday;
  dateIndex: number;
};

export const WEEKDAYS: WeekdayConfig[] = [
  { value: "monday", dateIndex: 1 },
  { value: "tuesday", dateIndex: 2 },
  { value: "wednesday", dateIndex: 3 },
  { value: "thursday", dateIndex: 4 },
  { value: "friday", dateIndex: 5 },
  { value: "saturday", dateIndex: 6 },
  { value: "sunday", dateIndex: 0 },
];

const WEEKDAY_ORDER = Object.fromEntries(
  WEEKDAYS.map((item, index) => [item.value, index])
) as Record<RecurrenceWeekday, number>;

/** The `dates:recurrenceSummary.*` unit keys for each frequency. */
const FREQUENCY_LABELS: Record<RecurrenceFrequency, { singular: string; plural: string }> = {
  hourly: { singular: "hour", plural: "hours" },
  daily: { singular: "day", plural: "days" },
  weekly: { singular: "week", plural: "weeks" },
  monthly: { singular: "month", plural: "months" },
  yearly: { singular: "year", plural: "years" },
};

export const getReferenceDate = (value?: string | null): Date => {
  if (!value) {
    return new Date();
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return new Date();
  }
  return parsed;
};

export const getWeekdayFromDate = (date: Date): RecurrenceWeekday => {
  // Normalize to midnight local time to get the date's weekday regardless of time
  const normalized = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = normalized.getDay(); // 0 (Sun) - 6 (Sat)
  const match = WEEKDAYS.find((weekday) => weekday.dateIndex === day);
  return match ? match.value : "monday";
};

export const getWeekPosition = (date: Date): TaskWeekPosition => {
  const day = date.getDate();
  const daysInMonth = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  if (day + 7 > daysInMonth) {
    return "last";
  }
  const index = Math.ceil(day / 7);
  return (["first", "second", "third", "fourth", "fifth"][index - 1] ?? "last") as TaskWeekPosition;
};

const sortWeekdays = (weekdays: RecurrenceWeekday[]) =>
  [...new Set(weekdays)].sort((a, b) => WEEKDAY_ORDER[a] - WEEKDAY_ORDER[b]);

const baseRule = (): RecurrenceRule => ({
  frequency: "daily",
  interval: 1,
  weekdays: [],
  monthly_mode: "day_of_month",
  month_days: [],
  months: [],
  weekday_position: null,
  weekday: null,
  set_position: "last",
  ends: "never",
  end_after_occurrences: null,
  end_date: null,
});

export const createRecurrenceFromPreset = (
  preset: RecurrencePreset,
  referenceDate?: string | null
): RecurrenceRule | null => {
  const anchor = getReferenceDate(referenceDate);
  switch (preset) {
    case "none":
      return null;
    case "hourly":
      return { ...baseRule(), frequency: "hourly" };
    case "daily":
      return baseRule();
    case "weekly":
      return {
        ...baseRule(),
        frequency: "weekly",
        weekdays: [getWeekdayFromDate(anchor)],
      };
    case "weekdays":
      return {
        ...baseRule(),
        frequency: "weekly",
        weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
      };
    case "monthly":
      return {
        ...baseRule(),
        frequency: "monthly",
        month_days: [anchor.getDate()],
      };
    case "yearly":
      return {
        ...baseRule(),
        frequency: "yearly",
        month_days: [anchor.getDate()],
        months: [anchor.getMonth() + 1],
      };
    case "custom":
      return baseRule();
    default:
      return null;
  }
};

export const detectRecurrencePreset = (rule: RecurrenceRule | null): RecurrencePreset => {
  if (!rule) {
    return "none";
  }
  if (rule.frequency === "hourly" && rule.interval === 1 && rule.ends === "never") return "hourly";
  if (rule.frequency === "daily" && rule.interval === 1 && rule.ends === "never") {
    return "daily";
  }
  if (rule.frequency === "weekly" && rule.interval === 1) {
    const weekdays = sortWeekdays(rule.weekdays);
    const weekdayPreset = ["monday", "tuesday", "wednesday", "thursday", "friday"];
    if (
      weekdays.length === weekdayPreset.length &&
      weekdays.every((day, index) => day === weekdayPreset[index])
    ) {
      return "weekdays";
    }
    if (weekdays.length === 1) {
      return "weekly";
    }
  }
  if (
    rule.frequency === "monthly" &&
    rule.interval === 1 &&
    rule.monthly_mode === "day_of_month" &&
    rule.month_days.length === 1 &&
    rule.month_days[0] > 0 &&
    rule.ends === "never"
  ) {
    return "monthly";
  }
  if (
    rule.frequency === "yearly" &&
    rule.interval === 1 &&
    rule.monthly_mode === "day_of_month" &&
    rule.month_days.length === 1 &&
    rule.month_days[0] > 0 &&
    rule.months.length === 1 &&
    rule.ends === "never"
  ) {
    return "yearly";
  }
  return "custom";
};

const formatWeekdayList = (weekdays: RecurrenceWeekday[], t: TranslateFn) =>
  formatList(
    sortWeekdays(weekdays).map((day) => t(`dates:weekdays.${day}`)),
    "conjunction"
  );

const formatList = (labels: string[], type: "conjunction" | "disjunction" = "conjunction") => {
  if (!labels.length) {
    return "";
  }
  if (labels.length === 1) {
    return labels[0] ?? "";
  }
  try {
    return listFormat(undefined, { style: "long", type }).format(labels);
  } catch {
    if (labels.length === 2) {
      return `${labels[0]} and ${labels[1]}`;
    }
    return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
  }
};

const formatEnding = (rule: RecurrenceRule, t: TranslateFn) => {
  if (rule.ends === "on_date" && rule.end_date) {
    // Parse date-only string as local date to avoid timezone issues
    const match = rule.end_date.match(/^(\d{4})-(\d{2})-(\d{2})/);
    const date = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
      : new Date(rule.end_date);
    if (!Number.isNaN(date.getTime())) {
      return t("dates:recurrenceSummary.untilDate", { date: dateTimeFormat().format(date) });
    }
  }
  if (rule.ends === "after_occurrences" && typeof rule.end_after_occurrences === "number") {
    return t("dates:recurrenceSummary.forOccurrences", { count: rule.end_after_occurrences });
  }
  return "";
};

const WORK_DAYS: RecurrenceWeekday[] = ["monday", "tuesday", "wednesday", "thursday", "friday"];

const describeMonthlyDetail = (rule: RecurrenceRule, t: TranslateFn) => {
  switch (rule.monthly_mode) {
    case "day_of_month": {
      const days = sortMonthDays(rule.month_days);
      if (!days.length) return "";
      if (days.length === 1) {
        return days[0] === -1
          ? t("dates:recurrenceSummary.onLastDay")
          : t("dates:recurrenceSummary.onDay", { day: days[0] });
      }
      return t("dates:recurrenceSummary.onDays", {
        days: formatList(
          days.map((day) => (day === -1 ? t("dates:recurrenceSummary.lastDayItem") : String(day)))
        ),
      });
    }
    case "weekday":
      return rule.weekday_position && rule.weekday
        ? t("dates:recurrenceSummary.onPositionWeekday", {
            position: t(`dates:positions.${rule.weekday_position}`),
            weekday: t(`dates:weekdays.${rule.weekday}`),
          })
        : "";
    case "weekdays":
      return rule.weekdays.length
        ? t("dates:recurrenceSummary.onEveryWeekdays", {
            weekdays: formatWeekdayList(rule.weekdays, t),
          })
        : "";
    case "set": {
      if (!rule.weekdays.length) return "";
      const workDays = sortWeekdays(rule.weekdays).join() === WORK_DAYS.join();
      const first = rule.set_position === "first";
      if (workDays) {
        return t(
          first ? "dates:recurrenceSummary.onFirstWorkDay" : "dates:recurrenceSummary.onLastWorkDay"
        );
      }
      const weekdays = formatList(
        sortWeekdays(rule.weekdays).map((day) => t(`dates:weekdays.${day}`)),
        "disjunction"
      );
      return t(first ? "dates:recurrenceSummary.onFirstOf" : "dates:recurrenceSummary.onLastOf", {
        weekdays,
      });
    }
    default:
      return "";
  }
};

export const summarizeRecurrence = (
  rule: RecurrenceRule | null,
  options:
    | {
        referenceDate?: string | null;
        strategy?: RecurrenceStrategy;
        limit?: number | null;
      }
    | undefined,
  t: TranslateFn
): string => {
  if (!rule) {
    return t("dates:recurrenceSummary.doesNotRepeat");
  }

  const frequencyLabel = FREQUENCY_LABELS[rule.frequency];
  const unit =
    rule.interval === 1
      ? t(`dates:recurrenceSummary.${frequencyLabel.singular}`)
      : t(`dates:recurrenceSummary.${frequencyLabel.plural}`);
  const schedule =
    rule.frequency === "hourly" && rule.interval === 1
      ? t("dates:recurrenceSummary.everyHour")
      : rule.interval === 1
        ? t("dates:recurrenceSummary.everySingular", { unit })
        : t("dates:recurrenceSummary.everyPlural", { count: rule.interval, unit });

  let detail = "";
  switch (rule.frequency) {
    case "weekly":
      if (rule.weekdays.length) {
        detail = t("dates:recurrenceSummary.onWeekdays", {
          weekdays: formatWeekdayList(rule.weekdays, t),
        });
      }
      break;
    case "monthly":
      detail = describeMonthlyDetail(rule, t);
      break;
    case "yearly": {
      const months = rule.months.length
        ? [...rule.months].sort((a, b) => a - b)
        : options?.referenceDate
          ? [getReferenceDate(options.referenceDate).getMonth() + 1]
          : [];
      const monthName = formatList(months.map((month) => t(`dates:months.${month}`)));
      const monthlyDetail = describeMonthlyDetail(rule, t);
      if (monthName && monthlyDetail) {
        detail = t("dates:recurrenceSummary.detailOfMonth", {
          detail: monthlyDetail,
          month: monthName,
        });
      } else if (monthName) {
        detail = t("dates:recurrenceSummary.inMonth", { month: monthName });
      } else {
        detail = monthlyDetail;
      }
      break;
    }
    default:
      detail = "";
  }

  const parts = [t("dates:recurrenceSummary.repeats", { schedule })];
  if (options?.strategy === "rolling") {
    parts.push(`(${t("dates:recurrenceSummary.afterCompletion")})`);
    if (rule.frequency === "hourly" && options.limit != null) {
      parts.push(t("dates:recurrenceSummary.dailyLimit", { count: options.limit }));
    }
  }
  if (detail) {
    parts.push(detail);
  }
  const ending = formatEnding(rule, t);
  if (ending) {
    parts.push(ending);
  }

  return parts.join(" ");
};

/** Month days in order: the numbered ones, then the last. */
export const sortMonthDays = (days: number[]) =>
  [...new Set(days)].sort((a, b) => (a === -1 ? 32 : a) - (b === -1 ? 32 : b));

/**
 * A monthly or yearly repeat moved to another way of picking its days, the
 * fields that way needs taken from the start where it has none yet.
 */
export const withMonthlyMode = (
  rule: RecurrenceRule,
  mode: MonthlyMode,
  referenceDate?: string | null
): RecurrenceRule => {
  const anchor = getReferenceDate(referenceDate);
  const weekday = getWeekdayFromDate(anchor);
  switch (mode) {
    case "day_of_month":
      return {
        ...rule,
        monthly_mode: mode,
        month_days: rule.month_days.length ? rule.month_days : [anchor.getDate()],
      };
    case "weekday":
      return {
        ...rule,
        monthly_mode: mode,
        weekday: rule.weekday ?? weekday,
        weekday_position: rule.weekday_position ?? getWeekPosition(anchor),
      };
    case "weekdays":
      return {
        ...rule,
        monthly_mode: mode,
        weekdays: rule.weekdays.length ? rule.weekdays : [weekday],
      };
    case "set":
      return { ...rule, monthly_mode: mode, weekdays: WORK_DAYS };
  }
};

/** A repeat moved to another frequency, keeping how often and when it ends. */
export const withFrequency = (
  rule: RecurrenceRule,
  frequency: RecurrenceFrequency,
  referenceDate?: string | null
): RecurrenceRule => {
  const anchor = getReferenceDate(referenceDate);
  const next: RecurrenceRule = {
    ...baseRule(),
    frequency,
    ends: rule.ends,
    end_after_occurrences: rule.end_after_occurrences,
    end_date: rule.end_date,
  };
  if (frequency === "weekly") {
    return { ...next, weekdays: [getWeekdayFromDate(anchor)] };
  }
  if (frequency === "monthly" || frequency === "yearly") {
    return {
      ...next,
      month_days: [anchor.getDate()],
      months: frequency === "yearly" ? [anchor.getMonth() + 1] : [],
    };
  }
  return next;
};

// ---------------------------------------------------------------------------
// RRULE lines
// ---------------------------------------------------------------------------

const CODES: Record<RecurrenceWeekday, string> = {
  monday: "MO",
  tuesday: "TU",
  wednesday: "WE",
  thursday: "TH",
  friday: "FR",
  saturday: "SA",
  sunday: "SU",
};
const CODE_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const WEEKDAY_OF = Object.fromEntries(
  Object.entries(CODES).map(([name, code]) => [code, name])
) as Record<string, RecurrenceWeekday>;
const POSITION_NUMBERS: Record<TaskWeekPosition, number> = {
  first: 1,
  second: 2,
  third: 3,
  fourth: 4,
  fifth: 5,
  last: -1,
};
const POSITION_OF = Object.fromEntries(
  Object.entries(POSITION_NUMBERS).map(([name, n]) => [n, name])
) as Record<number, TaskWeekPosition>;

/**
 * An all-day event's stored start as the form reads a date: its UTC date, at
 * local midnight, so it is that day in every zone.
 */
export const allDayReference = (start: string) => `${start.slice(0, 10)}T00:00:00`;

const pad = (n: number) => String(n).padStart(2, "0");

/** The longest one step of each frequency takes, in days, as the server counts it. */
const STEP_DAYS: Record<RecurrenceFrequency, number> = {
  hourly: 1 / 24,
  daily: 1,
  weekly: 7,
  monthly: 31,
  yearly: 366,
};

/** The most times a repeat can happen: ten thousand, ending within a hundred
 * years of its first. */
export const maxOccurrences = (rule: RecurrenceRule) =>
  Math.min(10000, Math.floor((100 * 366) / (STEP_DAYS[rule.frequency] * rule.interval)) + 1);

/** One clamped day in each chosen month, independent of leap years. January
 * uses its year-day; later months count back from year end so February's leap
 * day cannot move them. A clamped February date is its last day in either year. */
const yearlyClampedDays = (months: number[], day: number): number[] =>
  [...new Set(months)]
    .map((month) => {
      if (month === 1) return day;
      const last = new Date(Date.UTC(2001, month, 0)).getUTCDate();
      return (Date.UTC(2001, month - 1, Math.min(day, last)) - Date.UTC(2002, 0, 1)) / 86_400_000;
    })
    .sort((a, b) => a - b);

/**
 * The RRULE for a rule as picked. Send it with `tz: browserTimezone()`, the
 * zone its days are in. An all-day event ends on a date.
 */
export const toRRule = (rule: RecurrenceRule, options?: { allDay?: boolean }): string => {
  const parts = [`FREQ=${rule.frequency.toUpperCase()}`];
  if (rule.interval > 1) parts.push(`INTERVAL=${rule.interval}`);
  if (rule.frequency === "weekly" && rule.weekdays.length) {
    parts.push(
      `BYDAY=${sortWeekdays(rule.weekdays)
        .map((day) => CODES[day])
        .join(",")}`
    );
  }
  if (rule.frequency === "monthly" || rule.frequency === "yearly") {
    const weekdays = sortWeekdays(rule.weekdays)
      .map((day) => CODES[day])
      .join(",");
    const days = sortMonthDays(rule.month_days);
    if (rule.monthly_mode === "weekday" && rule.weekday && rule.weekday_position) {
      parts.push(`BYDAY=${POSITION_NUMBERS[rule.weekday_position]}${CODES[rule.weekday]}`);
    } else if (rule.monthly_mode === "weekdays" && weekdays) {
      parts.push(`BYDAY=${weekdays}`);
    } else if (rule.monthly_mode === "set" && weekdays) {
      parts.push(`BYDAY=${weekdays}`, `BYSETPOS=${rule.set_position === "first" ? 1 : -1}`);
    } else if (rule.monthly_mode === "day_of_month" && days.length === 1 && days[0] > 28) {
      // A day a short month lacks falls on that month's last day.
      parts.push(`BYMONTHDAY=${Array.from({ length: days[0] - 27 }, (_, i) => 28 + i).join(",")}`);
      if (rule.frequency === "yearly" && new Set(rule.months).size > 1) {
        // BYSETPOS would select only once across the entire year. Explicit
        // year-days select the clamped date independently in every month.
        parts.push(`BYYEARDAY=${yearlyClampedDays(rule.months, days[0]).join(",")}`);
      } else {
        parts.push("BYSETPOS=-1");
      }
    } else if (rule.monthly_mode === "day_of_month" && days.length) {
      parts.push(`BYMONTHDAY=${days.join(",")}`);
    }
    if (rule.frequency === "yearly" && rule.months.length) {
      parts.push(`BYMONTH=${[...new Set(rule.months)].sort((a, b) => a - b).join(",")}`);
    }
  }
  if (rule.ends === "after_occurrences" && rule.end_after_occurrences) {
    parts.push(`COUNT=${rule.end_after_occurrences}`);
  } else if (rule.ends === "on_date" && rule.end_date) {
    const [y, m, d] = rule.end_date.slice(0, 10).split("-").map(Number);
    if (options?.allDay) {
      parts.push(`UNTIL=${y}${pad(m)}${pad(d)}`);
    } else {
      // The end of the picked day, where it is picked.
      const u = new Date(y, m - 1, d, 23, 59, 59);
      const day = `${u.getUTCFullYear()}${pad(u.getUTCMonth() + 1)}${pad(u.getUTCDate())}`;
      parts.push(
        `UNTIL=${day}T${pad(u.getUTCHours())}${pad(u.getUTCMinutes())}${pad(u.getUTCSeconds())}Z`
      );
    }
  }
  return `RRULE:${parts.join(";")}`;
};

type Parts = Map<string, string[]>;

const parseRule = (text: string): Parts | null => {
  const line = text
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.startsWith("RRULE:"));
  // A rule with skipped or extra dates is more than the form edits.
  if (!line || text.includes("EXDATE") || text.includes("RDATE")) return null;
  const parts: Parts = new Map();
  for (const part of line.slice("RRULE:".length).split(";")) {
    const [key, value] = part.split("=");
    if (key && value !== undefined) parts.set(key, value.split(","));
  }
  return parts;
};

const utcDayNumber = (date: Date) =>
  Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 86_400_000;
const localDayNumber = (date: Date) =>
  Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000;

// The nth weekday falls on one stretch of the month: 1–7 for the first, 29–31
// for the fifth, -7 to -1 for the last.
const stretch = (ordinal: number): number[] =>
  ordinal > 0
    ? Array.from(
        { length: Math.min(7 * ordinal, 31) - 7 * (ordinal - 1) },
        (_, i) => 7 * (ordinal - 1) + 1 + i
      )
    : Array.from({ length: 7 }, (_, i) => 7 * ordinal + i);

const moveMonthday = (day: number, days: number): number => {
  const moved = day + days;
  if (day > 0 && moved === 0) return -1;
  if (day < 0 && moved === 0) return 1;
  return moved > 31 ? 1 : moved;
};

/**
 * A stored rule's days read in the viewer's zone. They are the days it was
 * picked on, which the start moved by its shift lands on; a viewer elsewhere
 * sees them moved by the day between that and their own date. Where that move
 * leaves a shape the form can't show, the rule reads as custom (`null`): the
 * first or last of some weekdays, or every one of them in a month, moves
 * across a month's end on some months and not others.
 */
const toLocalParts = (parts: Parts, start: Date, shift: number): Parts | null => {
  const picked = new Date(start.getTime() + shift * 60_000);
  const days = localDayNumber(start) - utcDayNumber(picked);
  if (!days) return parts;
  // A viewer-day shift can cross a year boundary. Keep year-day rules custom
  // rather than pretending an unchanged year-day still represents the form.
  if (parts.has("BYYEARDAY")) return null;
  const moved: Parts = new Map(parts);
  const byday = parts.get("BYDAY") ?? [];
  const monthly = ["MONTHLY", "YEARLY"].includes(parts.get("FREQ")?.[0] ?? "");
  if (
    (parts.has("BYSETPOS") && parts.has("BYDAY")) ||
    (monthly &&
      byday.length &&
      byday.every((code) => code.length === 2) &&
      !parts.has("BYMONTHDAY"))
  ) {
    return null;
  }
  let monthdays = (parts.get("BYMONTHDAY") ?? []).map(Number);
  const shiftCode = (code: string) =>
    CODE_ORDER[(CODE_ORDER.indexOf(code.slice(-2)) + days + 7) % 7];
  if (byday.length === 1 && byday[0].length > 2 && !monthdays.length) {
    monthdays = stretch(Number(byday[0].slice(0, -2)));
  }
  if (byday.length)
    moved.set(
      "BYDAY",
      byday.map((code) => shiftCode(code))
    );
  if (monthdays.length) {
    const next = [...new Set(monthdays.map((day) => moveMonthday(day, days)))];
    const sorted = [
      ...next.filter((d) => d > 0).sort((a, b) => a - b),
      ...next.filter((d) => d < 0).sort((a, b) => a - b),
    ];
    const ordinal = [1, 2, 3, 4, 5, -1].find((n) => stretch(n).join() === sorted.join());
    if (byday.length === 1 && ordinal !== undefined) {
      moved.set("BYDAY", [`${ordinal}${shiftCode(byday[0])}`]);
      moved.delete("BYMONTHDAY");
    } else {
      moved.set("BYMONTHDAY", sorted.map(String));
    }
    const month = parts.get("BYMONTH");
    const crossing = monthdays.every(
      (day) => (day === 1 && days < 0) || ((day === -1 || day === 31) && days > 0)
    );
    if (month && crossing) {
      moved.set(
        "BYMONTH",
        month.map((m) => String(((Number(m) - 1 + days + 12) % 12) + 1))
      );
    }
  }
  return moved;
};

/**
 * The rule the form edits, from a stored rule and its series start (an event's
 * start, a task's due date): `null` for no repeat, `"custom"` for one the form
 * can't show, which is kept as it is until somebody picks another. An all-day
 * event's days are UTC dates, the same for every viewer, so they are read as
 * they are.
 */
export const fromStored = (
  stored: string | null | undefined,
  start: string | null | undefined,
  shift = 0,
  allDay = false,
  allowHourly = false
): RecurrenceRule | "custom" | null => {
  if (!stored) return null;
  const raw = parseRule(stored);
  if (!raw) return "custom";
  const parts = start && !allDay ? toLocalParts(raw, new Date(start), shift) : raw;
  if (!parts) return "custom";
  const freq = (parts.get("FREQ")?.[0] ?? "").toLowerCase() as RecurrenceFrequency;
  if (!(freq in FREQUENCY_LABELS) || (freq === "hourly" && !allowHourly)) return "custom";
  const known = new Set([
    "FREQ",
    "INTERVAL",
    "COUNT",
    "UNTIL",
    "BYDAY",
    "BYMONTHDAY",
    "BYMONTH",
    "BYSETPOS",
    "BYYEARDAY",
  ]);
  if ([...parts.keys()].some((key) => !known.has(key))) return "custom";

  const rule: RecurrenceRule = {
    ...baseRule(),
    frequency: freq,
    interval: Number(parts.get("INTERVAL")?.[0] ?? 1),
  };
  const byday = parts.get("BYDAY") ?? [];
  const monthdays = (parts.get("BYMONTHDAY") ?? []).map(Number);
  const setpos = parts.get("BYSETPOS");
  const yeardays = (parts.get("BYYEARDAY") ?? []).map(Number);
  const months = (parts.get("BYMONTH") ?? []).map(Number);
  const clampedDay = 27 + monthdays.length;
  const clampedYear =
    freq === "yearly" &&
    months.length > 1 &&
    months.every((month) => month >= 1 && month <= 12) &&
    !byday.length &&
    !setpos &&
    clampedDay >= 29 &&
    clampedDay <= 31 &&
    monthdays.every((day, index) => day === 28 + index) &&
    yearlyClampedDays(months, clampedDay).join() === [...yeardays].sort((a, b) => a - b).join();
  if (yeardays.length && !clampedYear) return "custom";
  if (freq === "weekly") {
    if (monthdays.length || setpos || byday.some((code) => !WEEKDAY_OF[code])) return "custom";
    rule.weekdays = byday.map((code) => WEEKDAY_OF[code]);
  } else if (freq === "monthly" || freq === "yearly") {
    const plain = byday.length > 0 && byday.every((code) => WEEKDAY_OF[code]);
    const position = byday.length === 1 ? POSITION_OF[Number(byday[0].slice(0, -2))] : undefined;
    if (clampedYear) {
      rule.month_days = [clampedDay];
    } else if (position && !monthdays.length && !setpos) {
      rule.monthly_mode = "weekday";
      rule.weekday_position = position;
      rule.weekday = WEEKDAY_OF[byday[0].slice(-2)] ?? null;
    } else if (plain && !monthdays.length && !setpos) {
      rule.monthly_mode = "weekdays";
      rule.weekdays = sortWeekdays(byday.map((code) => WEEKDAY_OF[code]));
    } else if (
      plain &&
      !monthdays.length &&
      freq === "monthly" &&
      (setpos?.join() === "1" || setpos?.join() === "-1")
    ) {
      rule.monthly_mode = "set";
      rule.weekdays = sortWeekdays(byday.map((code) => WEEKDAY_OF[code]));
      rule.set_position = setpos.join() === "1" ? "first" : "last";
    } else if (
      !byday.length &&
      setpos?.join() === "-1" &&
      monthdays[0] === 28 &&
      monthdays.every((day, i) => day === 28 + i) &&
      monthdays.length <= 4
    ) {
      rule.month_days = [27 + monthdays.length];
    } else if (
      !byday.length &&
      !setpos &&
      monthdays.length &&
      monthdays.every((day) => day === -1 || (day >= 1 && day <= 31)) &&
      // One day past 28 on its own skips short months, which the form's
      // single day doesn't: it falls on their last day.
      !(monthdays.length === 1 && monthdays[0] > 28)
    ) {
      rule.month_days = sortMonthDays(monthdays);
    } else if (byday.length || monthdays.length || setpos) {
      return "custom";
    }
    if (months.length && freq === "monthly") return "custom";
    rule.months = months;
  } else if (byday.length || monthdays.length || setpos || parts.has("BYMONTH")) {
    return "custom";
  }
  if (parts.has("COUNT")) {
    rule.ends = "after_occurrences";
    rule.end_after_occurrences = Number(parts.get("COUNT")?.[0]);
  } else if (parts.has("UNTIL")) {
    const value = parts.get("UNTIL")?.[0] ?? "";
    const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
    rule.ends = "on_date";
    // An instant's last day is the viewer's; a date is itself.
    rule.end_date =
      value.length > 8
        ? toLocalDateKey(
            new Date(`${iso}T${value.slice(9, 11)}:${value.slice(11, 13)}:${value.slice(13, 15)}Z`)
          )
        : iso;
  }
  return rule;
};

const toLocalDateKey = (date: Date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

/** A stored rule's summary for a list: the form's words, or a custom repeat. */
export const summarizeStored = (
  stored: string | null | undefined,
  start: string | null | undefined,
  options:
    | {
        strategy?: RecurrenceStrategy;
        shift?: number;
        allDay?: boolean;
        limit?: number | null;
      }
    | undefined,
  t: TranslateFn
): string => {
  const rule = fromStored(
    stored,
    start,
    options?.shift,
    options?.allDay,
    options?.strategy === "rolling"
  );
  if (rule === "custom") return t("dates:recurrenceSummary.custom");
  return summarizeRecurrence(
    rule,
    {
      referenceDate: options?.allDay && start ? allDayReference(start) : start,
      strategy: options?.strategy,
      limit: options?.limit,
    },
    t
  );
};

/**
 * The write fields for a repeat from the form: a picked rule with the zone its
 * days are in, `null` to stop repeating, or nothing for a custom rule, which
 * keeps what is stored.
 */
export const rulePayload = (
  rule: RecurrenceRule | "custom" | null,
  options?: { allDay?: boolean }
): { recurrence?: string | null; tz?: string } => {
  if (rule === "custom") return {};
  if (rule === null) return { recurrence: null };
  return { recurrence: toRRule(rule, options), tz: browserTimezone() };
};

/**
 * The shift the server keeps beside `rule` picked here for a series starting
 * at `start`, as `app.core.recurrence.shift_for` works it out: the browser's
 * offset for a rule of hours, otherwise the whole days between the start's
 * local date and its UTC one. What {@link fromStored} is given to read the rule
 * back as it was picked.
 */
export const shiftFor = (rule: RecurrenceRule, start: Date): number => {
  if (rule.frequency === "hourly") return -start.getTimezoneOffset();
  return (localDayNumber(start) - utcDayNumber(start)) * 1440;
};

/**
 * A task or event update with the browser's zone beside it, so a stored
 * repeat moves with a start that moved, its days kept where they were picked.
 */
export const withZone = <T extends object>(data: T): T & { tz?: string } => ({
  tz: browserTimezone(),
  ...data,
});
