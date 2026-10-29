/**
 * Reading a task's title for what else it says: "Send the invoice friday at
 * 3pm !high #billing @sam" is a task called "Send the invoice", due Friday at
 * three, high priority, tagged billing and given to Sam. "Bug: login broken"
 * is a bug, where the project has a type of that name.
 *
 * Pure: the words it knows, the tags, types and people it may name and the moment it
 * reads from are all handed in, so the same title always reads the same way.
 * The words come from the reader's language (`tasks:smartTitle.words`) and the
 * weekday and month names from the browser's, so a title is read in the
 * language it is typed in.
 */

import {
  addDays,
  addHours,
  addMonths,
  addWeeks,
  addYears,
  format,
  isValid,
  set,
  startOfDay,
  startOfMonth,
  startOfWeek,
  startOfYear,
} from "date-fns";

import type { TagSummary, TaskPriority, TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";
import {
  createRecurrenceFromPreset,
  isValidTaskRecurrence,
  type RecurrenceRule,
  type RecurrenceWeekday,
  WEEKDAYS,
} from "@/lib/recurrence";

// ── The words ───────────────────────────────────────────────────────────────

/** The words a title is read with, each a list of ways to say it. A phrase
 *  may be several words ("tous les"). */
export interface TitleWords {
  today: string[];
  tomorrow: string[];
  /** Before a weekday or a unit: "next friday", "next week". */
  next: string[];
  /** After one, where a language puts it there: "vendredi prochain". */
  nextAfter: string[];
  /** Before a count of units: "in 3 days". */
  in: string[];
  /** Before a repeat: "every week". Followed by `!` ("every!"), the repeat is
   *  counted from when each one is done. */
  every: string[];
  /** Every second one: "every other week". */
  other: string[];
  /** May come before a date, and goes with it: "due friday", "by friday". */
  lead: string[];
  /** May come before a time: "at 5pm". */
  at: string[];
  /** A count of one: "in a week". */
  one: string[];
  /** Between a day's number and its month: "30th of October". */
  of: string[];
  /** After a day's number: "30th". */
  ordinal: string[];
  day: string[];
  week: string[];
  month: string[];
  year: string[];
  /** Monday to Friday: "every weekday". */
  weekday: string[];
  /** Saturday and Sunday: "every weekend". */
  weekend: string[];
  hour: string[];
  /** Places in the month: "the third tuesday", "the last day". */
  first: string[];
  second: string[];
  third: string[];
  fourth: string[];
  fifth: string[];
  last: string[];
  /** After a place in the month, with `every` before it: "of the month". */
  ofTheMonth: string[];
  /** After one without `every`: "of every month", "each month". */
  ofEveryMonth: string[];
  /** Between two days: "mon and wed", "1st and 15th". */
  and: string[];
  /** Skipped before a day: "on the 15th". */
  the: string[];
  /** How a repeat ends: "until december 1", "10 times". */
  until: string[];
  times: string[];
  noon: string[];
  midnight: string[];
  am: string[];
  pm: string[];
  /** After an hour: "5 o'clock", "17 Uhr", "17h30". */
  oclock: string[];
  /** The reader: "@me". */
  me: string[];
  /** Monday to Sunday, as {@link WEEKDAYS} orders them: each day's full name
   *  and its short one. */
  weekdays: { long: string; short: string }[];
  /** January to December, each month's full name and its short one. */
  months: { long: string; short: string }[];
  /** What each priority may be called after `!`: its value and its label. */
  priorities: Record<TaskPriority, string[]>;
}

/** A word as it is compared: lower case, without accents. */
export const normalizeWord = (word: string): string =>
  word
    .normalize("NFD")
    .replace(/\p{Mn}/gu, "")
    .toLowerCase()
    .replace(/[’`]/g, "'");

const list = (value: string): string[] =>
  value
    .split("|")
    .map((each) => normalizeWord(each.trim()))
    .filter(Boolean);

export type WordKey = Exclude<keyof TitleWords, "weekdays" | "months" | "priorities">;

export const WORD_KEYS: WordKey[] = [
  "today",
  "tomorrow",
  "next",
  "nextAfter",
  "in",
  "every",
  "other",
  "lead",
  "at",
  "one",
  "of",
  "ordinal",
  "day",
  "week",
  "month",
  "year",
  "weekday",
  "weekend",
  "hour",
  "first",
  "second",
  "third",
  "fourth",
  "fifth",
  "last",
  "ofTheMonth",
  "ofEveryMonth",
  "and",
  "the",
  "until",
  "times",
  "noon",
  "midnight",
  "am",
  "pm",
  "oclock",
  "me",
];

/** A name as it is compared, without the dot some languages shorten with. */
const name = (value: string) => normalizeWord(value).replace(/\.$/, "");

/**
 * The words for a language: its own lists (each `|`-separated, as the
 * locale writes them) and the weekday and month names `locale` formats.
 */
export const titleWords = (
  words: Record<WordKey, string>,
  priorities: Record<TaskPriority, string>,
  locale: string
): TitleWords => {
  const named = (options: Intl.DateTimeFormatOptions, at: (index: number) => Date, count: number) =>
    Array.from({ length: count }, (_, index) => ({
      long: name(dateTimeFormat(locale, { ...options, timeZone: "UTC" }).format(at(index))),
      short: name(
        dateTimeFormat(locale, {
          [Object.keys(options)[0]]: "short",
          timeZone: "UTC",
        }).format(at(index))
      ),
    }));
  return {
    ...(Object.fromEntries(WORD_KEYS.map((key) => [key, list(words[key] ?? "")])) as Record<
      WordKey,
      string[]
    >),
    // 1 January 2024 was a Monday.
    weekdays: named({ weekday: "long" }, (index) => new Date(Date.UTC(2024, 0, 1 + index)), 7),
    months: named({ month: "long" }, (index) => new Date(Date.UTC(2024, index, 15)), 12),
    priorities: Object.fromEntries(
      (Object.keys(priorities) as TaskPriority[]).map((priority) => [
        priority,
        [...new Set([priority, ...list(priorities[priority])])],
      ])
    ) as Record<TaskPriority, string[]>,
  };
};

// ── What a title says ───────────────────────────────────────────────────────

/** Someone a title may give the task to. */
export interface TitlePerson {
  id: number;
  username: string;
  discriminator: number;
  display_name: string | null;
  avatar_url: string | null;
  status: string;
}

export type TitlePartType = "type" | "due" | "priority" | "repeat" | "tag" | "person";

/** A stretch of the title that was read as something. */
export interface TitlePart {
  type: TitlePartType;
  start: number;
  end: number;
  /** The words as typed. */
  text: string;
  /** Names it for {@link TitleReading.kept}: the same words read the same way. */
  key: string;
  /** The tag, person or task type it names. */
  id?: number;
}

export interface TitleReading {
  /** The title with what was read taken out of it. */
  title: string;
  parts: TitlePart[];
  due: Date | null;
  /** The due date was given a time of day, rather than the end of the day. */
  dueHasTime: boolean;
  priority: TaskPriority | null;
  repeat: RecurrenceRule | null;
  /** On schedule, or counted from when each one is done. */
  repeatStrategy: "fixed" | "rolling";
  tags: TagSummary[];
  people: TitlePerson[];
  /** The project's task type the title starts with: "bug: …". */
  type: TaskTypeRead | null;
}

export interface TitleContext {
  now: Date;
  words: TitleWords;
  /** 0 for Sunday: where "next week" starts. */
  weekStartsOn: number;
  /** The community's tags, which `#` names. */
  tags: TagSummary[];
  /** The project's task types, which a title may start with: "bug: …". */
  types: TaskTypeRead[];
  /** Who `@` may name, as far as they are known. */
  people: TitlePerson[];
  /** Who "@me" is. */
  me: TitlePerson | null;
  /** The parts kept as typed: their {@link TitlePart.key}s. A part inside
   *  one kept is kept too. */
  kept?: ReadonlySet<string>;
}

/** A title read for nothing: all of it is the title. */
const asTyped = (text: string): TitleReading => ({
  title: text.trim(),
  parts: [],
  due: null,
  dueHasTime: false,
  priority: null,
  repeat: null,
  repeatStrategy: "fixed",
  tags: [],
  people: [],
  type: null,
});

// ── Words in the title ──────────────────────────────────────────────────────

interface Word {
  start: number;
  /** Where its last letter ends, before the punctuation it is followed by. */
  end: number;
  /** As compared. */
  core: string;
  /** Followed straight away by `!`: "every!" repeats from when each is done. */
  bang: boolean;
}

const TRAILING = /[.,;:!?)\]]+$/;

const wordsOf = (text: string): Word[] =>
  [...text.matchAll(/\S+/g)].map((match) => {
    const raw = match[0];
    // A word that is only punctuation ("!" alone) keeps it.
    const trimmed = raw.replace(TRAILING, "") || raw;
    const lead = trimmed.match(/^[(["“]+/)?.[0].length ?? 0;
    return {
      start: match.index + lead,
      end: match.index + trimmed.length,
      core: normalizeWord(trimmed.slice(lead)),
      bang: raw.slice(trimmed.length).startsWith("!"),
    };
  });

/** How many words from `at` say one of `phrases`, the longest that fits; 0 for none. */
const phrase = (words: Word[], at: number, phrases: string[]): number => {
  let best = 0;
  for (const each of phrases) {
    const parts = each.split(/\s+/);
    if (parts.length <= best) continue;
    if (parts.every((part, offset) => words[at + offset]?.core === part)) best = parts.length;
  }
  return best;
};

// ── Dates ───────────────────────────────────────────────────────────────────

type Unit = "day" | "week" | "month" | "year";
const UNITS: Unit[] = ["day", "week", "month", "year"];

const add = (date: Date, unit: Unit, count: number) =>
  ({ day: addDays, week: addWeeks, month: addMonths, year: addYears })[unit](date, count);

/** The weekday a word names, as an index into {@link WEEKDAYS}. A shortening
 *  ("fri") counts only where `short` says it may: alone, "sun" is more often
 *  the sun than Sunday. */
const weekdayOf = (words: TitleWords, word: string | undefined, short: boolean): number => {
  if (!word) return -1;
  return words.weekdays.findIndex(
    (day) =>
      word === day.long ||
      word === `${day.long}s` ||
      (short && (word === day.short || (word.length >= 3 && day.long.startsWith(word))))
  );
};

const monthOf = (words: TitleWords, word: string | undefined): number => {
  if (!word || word.length < 3) return -1;
  return words.months.findIndex(
    (month) => word === month.long || word === month.short || month.long.startsWith(word)
  );
};

const unitOf = (words: TitleWords, all: Word[], at: number): [Unit, number] | null => {
  for (const unit of UNITS) {
    const length = phrase(all, at, words[unit]);
    if (length) return [unit, length];
  }
  return null;
};

/** The `WEEKDAYS` index of a date. */
const weekdayIndex = (date: Date) => (date.getDay() + 6) % 7;

/** The next `weekday` from `today`, today included. */
const upcoming = (today: Date, weekday: number) =>
  addDays(today, (weekday - weekdayIndex(today) + 7) % 7);

/** `weekday` in the week after this one. */
const inNextWeek = (today: Date, weekday: number, weekStartsOn: number) => {
  const nextWeek = startOfWeek(addWeeks(today, 1), {
    weekStartsOn: weekStartsOn as 0 | 1 | 2 | 3 | 4 | 5 | 6,
  });
  return upcoming(nextWeek, weekday);
};

/** A count of units: digits, or a word for one. */
const countOf = (words: TitleWords, all: Word[], at: number): [number, number] | null => {
  const word = all[at]?.core;
  if (word && /^\d{1,3}$/.test(word)) return [Number(word), 1];
  const one = phrase(all, at, words.one);
  return one ? [1, one] : null;
};

/** A day of the month as typed: "30", "30th", "30.". */
const dayNumber = (words: TitleWords, word: string | undefined): number | null => {
  const match = word?.match(/^(\d{1,2})(\p{L}*)$/u);
  if (!match) return null;
  if (match[2] && !words.ordinal.includes(match[2])) return null;
  const day = Number(match[1]);
  return day >= 1 && day <= 31 ? day : null;
};

/** A calendar date, rolled to next year when this year's has passed. */
const onDay = (today: Date, year: number | null, month: number, day: number): Date | null => {
  const date = new Date(year ?? today.getFullYear(), month, day);
  if (date.getMonth() !== month) return null;
  return year === null && date < today ? new Date(today.getFullYear() + 1, month, day) : date;
};

const yearAt = (all: Word[], at: number): number | null => {
  const word = all[at]?.core;
  return word && /^\d{4}$/.test(word) ? Number(word) : null;
};

interface Found<T> {
  value: T;
  /** The words it took. */
  length: number;
}

/** A date, said one of the ways a title says one, starting at `at`. */
const dateAt = (
  words: TitleWords,
  all: Word[],
  at: number,
  today: Date,
  weekStartsOn: number,
  led: boolean
): Found<Date> | null => {
  const word = all[at]?.core;
  if (!word) return null;
  let length = phrase(all, at, words.today);
  if (length) return { value: today, length };
  length = phrase(all, at, words.tomorrow);
  if (length) return { value: addDays(today, 1), length };

  // "2026-10-30"
  const iso = word.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (iso) {
    const date = onDay(today, Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
    return date ? { value: date, length: 1 } : null;
  }

  // "next friday", "next week"
  const next = phrase(all, at, words.next);
  if (next) {
    const weekday = weekdayOf(words, all[at + next]?.core, true);
    if (weekday >= 0) {
      return { value: inNextWeek(today, weekday, weekStartsOn), length: next + 1 };
    }
    const unit = unitOf(words, all, at + next);
    if (unit) return { value: startOfUnit(today, unit[0], weekStartsOn), length: next + unit[1] };
    return null;
  }

  // "in 3 days", "in a week"
  const into = phrase(all, at, words.in);
  if (into) {
    const count = countOf(words, all, at + into);
    const unit = count && unitOf(words, all, at + into + count[1]);
    if (count && unit) {
      return { value: add(today, unit[0], count[0]), length: into + count[1] + unit[1] };
    }
    return null;
  }

  // "friday", "vendredi prochain"
  const weekday = weekdayOf(words, word, led);
  if (weekday >= 0) {
    const after = phrase(all, at + 1, words.nextAfter);
    return after
      ? { value: inNextWeek(today, weekday, weekStartsOn), length: 1 + after }
      : { value: upcoming(today, weekday), length: 1 };
  }

  // "semaine prochaine"
  const unit = unitOf(words, all, at);
  if (unit) {
    const after = phrase(all, at + unit[1], words.nextAfter);
    if (after) {
      return { value: startOfUnit(today, unit[0], weekStartsOn), length: unit[1] + after };
    }
  }

  // "oct 30", "october 30th 2027"
  const month = monthOf(words, word);
  if (month >= 0) {
    const day = dayNumber(words, all[at + 1]?.core);
    if (day !== null) {
      const year = yearAt(all, at + 2);
      const date = onDay(today, year, month, day);
      return date ? { value: date, length: year === null ? 2 : 3 } : null;
    }
    return null;
  }

  // "30 oct", "30th of october", "30. Oktober", "30 de octubre"
  const day = dayNumber(words, word);
  if (day !== null) {
    const of = phrase(all, at + 1, words.of);
    const named = monthOf(words, all[at + 1 + of]?.core);
    if (named >= 0) {
      const year = yearAt(all, at + 2 + of);
      const date = onDay(today, year, named, day);
      return date ? { value: date, length: 2 + of + (year === null ? 0 : 1) } : null;
    }
  }
  return null;
};

/** Where the next week, month or year starts; tomorrow for "next day". */
const startOfUnit = (today: Date, unit: Unit, weekStartsOn: number): Date => {
  switch (unit) {
    case "day":
      return addDays(today, 1);
    case "week":
      return startOfWeek(addWeeks(today, 1), {
        weekStartsOn: weekStartsOn as 0 | 1 | 2 | 3 | 4 | 5 | 6,
      });
    case "month":
      return startOfMonth(addMonths(today, 1));
    case "year":
      return startOfYear(addYears(today, 1));
  }
};

// ── Times ───────────────────────────────────────────────────────────────────

type Time = { hours: number; minutes: number };

const clock = (hours: number, minutes: number, half: "am" | "pm" | null): Time | null => {
  if (minutes > 59) return null;
  if (half) {
    if (hours < 1 || hours > 12) return null;
    return { hours: (hours % 12) + (half === "pm" ? 12 : 0), minutes };
  }
  return hours > 23 ? null : { hours, minutes };
};

/** A time of day starting at `at`: "5pm", "5:30 pm", "17:00", "at 5",
 *  "noon", "17 Uhr", "17h30". */
const timeAt = (words: TitleWords, all: Word[], at: number): Found<Time> | null => {
  const lead = phrase(all, at, words.at);
  const start = at + lead;
  const word = all[start]?.core;
  if (!word) return null;
  let length = phrase(all, start, words.noon);
  if (length) return { value: { hours: 12, minutes: 0 }, length: lead + length };
  length = phrase(all, start, words.midnight);
  if (length) return { value: { hours: 23, minutes: 59 }, length: lead + length };

  // "a.m." loses its last dot to the punctuation a word ends with.
  const bare = (each: string) => each.replace(/\./g, "");
  const halfOf = (suffix: string): "am" | "pm" | null =>
    words.am.some((each) => bare(each) === bare(suffix))
      ? "am"
      : words.pm.some((each) => bare(each) === bare(suffix))
        ? "pm"
        : null;

  // "5pm", "5:30pm", "17h30"
  const joined = word.match(/^(\d{1,2})(?::(\d{2}))?([\p{L}.]+)(\d{2})?$/u);
  if (joined) {
    const [, hours, minutes, suffix, after] = joined;
    const half = halfOf(suffix);
    if (half && !after) {
      const time = clock(Number(hours), Number(minutes ?? 0), half);
      return time ? { value: time, length: lead + 1 } : null;
    }
    if (words.oclock.includes(suffix) && !minutes) {
      const time = clock(Number(hours), Number(after ?? 0), null);
      return time ? { value: time, length: lead + 1 } : null;
    }
    return null;
  }

  // "5 pm", "5:30", "17 Uhr", and a bare hour after "at"
  const plain = word.match(/^(\d{1,2})(?::(\d{2}))?$/);
  if (!plain) return null;
  const [, hours, minutes] = plain;
  const next = all[start + 1]?.core;
  const half = next ? halfOf(next) : null;
  if (half) {
    const time = clock(Number(hours), Number(minutes ?? 0), half);
    return time ? { value: time, length: lead + 2 } : null;
  }
  const oclock = phrase(all, start + 1, words.oclock);
  if (oclock || minutes !== undefined || lead) {
    const time = clock(Number(hours), Number(minutes ?? 0), null);
    return time ? { value: time, length: lead + 1 + oclock } : null;
  }
  return null;
};

// ── Repeats ─────────────────────────────────────────────────────────────────

/**
 * A repeat as said. Its rule is the repeat editor's own ({@link RecurrenceRule}),
 * written out by the same `toRRule`, so a title can say only what the editor
 * can show and the server takes. Some rules take a day from the date they start
 * on ("every month" is that day each month), so the rule is made once it is known.
 */
interface Repeat {
  rule: (start: Date) => RecurrenceRule;
  /** Counted from when each one is done: an hourly repeat is never on schedule. */
  rolling: boolean;
  /** A plain interval ("2 weeks") as it is counted from completion: the unit
   *  alone, with no day taken from the start, so the gap runs from the day it
   *  was done rather than to the start's weekday. */
  counted?: RecurrenceRule;
}

/** The server's bounds on a repeat's interval and count. */
const MAX_INTERVAL = 366;
const MAX_COUNT = 10_000;

const POSITIONS = ["first", "second", "third", "fourth", "fifth"] as const;
type Position = (typeof POSITIONS)[number] | "last";

const MON_TO_FRI: RecurrenceWeekday[] = ["monday", "tuesday", "wednesday", "thursday", "friday"];

const blank = (): RecurrenceRule => {
  const rule = createRecurrenceFromPreset("custom");
  if (!rule) throw new Error("A custom repeat has a rule.");
  return rule;
};

/** "third", "3rd", "last": a place in the month, and the words it took. */
const positionAt = (words: TitleWords, all: Word[], at: number): Found<Position> | null => {
  for (const position of [...POSITIONS, "last"] as const) {
    const length = phrase(all, at, words[position]);
    if (length) return { value: position, length };
  }
  const match = all[at]?.core.match(/^([1-5])(\p{L}+)$/u);
  if (match && words.ordinal.includes(match[2])) {
    return { value: POSITIONS[Number(match[1]) - 1], length: 1 };
  }
  return null;
};

/** Words skipped before what follows them: "on the", "the". */
const filler = (words: TitleWords, all: Word[], at: number): number => {
  let length = 0;
  for (;;) {
    const more = phrase(all, at + length, words.lead) || phrase(all, at + length, words.the);
    if (!more) return length;
    length += more;
  }
};

/** "of the month", or with `every` only "of every month", "each month". */
const monthPhrase = (words: TitleWords, all: Word[], at: number, any: boolean): number =>
  phrase(all, at, words.ofEveryMonth) || (any ? phrase(all, at, words.ofTheMonth) : 0);

/** Weekdays in a row: "monday", "mon, wed and fri". */
const weekdaysAt = (words: TitleWords, all: Word[], at: number): Found<number[]> | null => {
  const days: number[] = [];
  let next = at;
  for (;;) {
    const day = weekdayOf(words, all[next]?.core, true);
    if (day < 0) break;
    if (!days.includes(day)) days.push(day);
    next += 1;
    const and = phrase(all, next, words.and);
    if (and && weekdayOf(words, all[next + and]?.core, true) >= 0) next += and;
  }
  return days.length ? { value: days, length: next - at } : null;
};

/** Days of the month in a row: "15th", "1st and 15th". Bare numbers count only
 *  where `bare` says a month phrase follows. */
const monthDaysAt = (
  words: TitleWords,
  all: Word[],
  at: number,
  bare: boolean
): Found<number[]> | null => {
  const days: number[] = [];
  let next = at;
  for (;;) {
    const word = all[next]?.core;
    const day = dayNumber(words, word);
    if (day === null || (!bare && /^\d+$/.test(word ?? ""))) break;
    if (!days.includes(day)) days.push(day);
    next += 1;
    const and = phrase(all, next, words.and);
    if (and && dayNumber(words, all[next + and]?.core) !== null) next += and;
  }
  return days.length ? { value: days, length: next - at } : null;
};

const monthly = (patch: Partial<RecurrenceRule>, interval: number): Repeat => ({
  rule: () => ({ ...blank(), frequency: "monthly", interval, ...patch }),
  rolling: false,
});

/**
 * A place in the month: "third tuesday", "last weekday", "last day", or days
 * by number, "15th", "1st and 15th". `bare` lets plain numbers count, where a
 * month phrase is known to follow.
 */
const inMonthAt = (
  words: TitleWords,
  all: Word[],
  at: number,
  interval: number,
  bare: boolean
): Found<Repeat> | null => {
  const position = positionAt(words, all, at);
  if (position) {
    const next = at + position.length;
    const weekday = weekdayOf(words, all[next]?.core, true);
    if (weekday >= 0) {
      return {
        value: monthly(
          {
            monthly_mode: "weekday",
            weekday: WEEKDAYS[weekday].value,
            weekday_position: position.value,
          },
          interval
        ),
        length: position.length + 1,
      };
    }
    const working = phrase(all, next, words.weekday);
    if (working && (position.value === "first" || position.value === "last")) {
      return {
        value: monthly(
          { monthly_mode: "set", weekdays: MON_TO_FRI, set_position: position.value },
          interval
        ),
        length: position.length + working,
      };
    }
    const day = phrase(all, next, words.day);
    if (day) {
      const index = position.value === "last" ? -1 : POSITIONS.indexOf(position.value) + 1;
      return {
        value: monthly({ monthly_mode: "day_of_month", month_days: [index] }, interval),
        length: position.length + day,
      };
    }
    // "1st" is a place and a day: what follows decides, and it is a day here.
  }
  const days = monthDaysAt(words, all, at, bare);
  if (days) {
    return {
      value: monthly({ monthly_mode: "day_of_month", month_days: days.value }, interval),
      length: days.length,
    };
  }
  return null;
};

/** A date each year: "oct 30", "30th of october". */
const yearDayAt = (words: TitleWords, all: Word[], at: number): Found<[number, number]> | null => {
  const month = monthOf(words, all[at]?.core);
  if (month >= 0) {
    const day = dayNumber(words, all[at + 1]?.core);
    return day === null ? null : { value: [month, day], length: 2 };
  }
  const day = dayNumber(words, all[at]?.core);
  if (day === null) return null;
  const of = phrase(all, at + 1, words.of);
  const named = monthOf(words, all[at + 1 + of]?.core);
  return named >= 0 ? { value: [named, day], length: 2 + of } : null;
};

const yearly = ([month, day]: [number, number], interval: number): Repeat => ({
  rule: () => ({
    ...blank(),
    frequency: "yearly",
    interval,
    monthly_mode: "day_of_month",
    month_days: [day],
    months: [month + 1],
  }),
  rolling: false,
});

const FREQUENCY_OF: Record<Unit, RecurrenceRule["frequency"]> = {
  day: "daily",
  week: "weekly",
  month: "monthly",
  year: "yearly",
};

const PRESET_OF: Record<Unit, "daily" | "weekly" | "monthly" | "yearly"> = {
  day: "daily",
  week: "weekly",
  month: "monthly",
  year: "yearly",
};

/** What follows `every` (and its interval), at `at`. */
const everyAt = (
  words: TitleWords,
  all: Word[],
  at: number,
  interval: number
): Found<Repeat> | null => {
  // "every 2 hours": counted from when each is done.
  const hours = phrase(all, at, words.hour);
  if (hours) {
    return {
      value: { rule: () => ({ ...blank(), frequency: "hourly", interval }), rolling: true },
      length: hours,
    };
  }
  if (interval === 1) {
    const working = phrase(all, at, words.weekday);
    if (working) {
      return {
        value: {
          rule: () => ({ ...blank(), frequency: "weekly", weekdays: MON_TO_FRI }),
          rolling: false,
        },
        length: working,
      };
    }
  }
  const weekend = phrase(all, at, words.weekend);
  if (weekend) {
    return {
      value: {
        rule: () => ({
          ...blank(),
          frequency: "weekly",
          interval,
          weekdays: ["saturday", "sunday"],
        }),
        rolling: false,
      },
      length: weekend,
    };
  }
  // "every third tuesday", "every last weekday", "every 15th"
  const inMonth = inMonthAt(words, all, at, interval, false);
  if (inMonth) return inMonth;
  // "every 15 of the month", "jeden 15. im Monat": a bare number, with the
  // month after it saying what it is.
  const plain = inMonthAt(words, all, at, interval, true);
  if (plain && monthPhrase(words, all, at + plain.length, true)) return plain;
  // "every mon, wed and fri"
  const days = weekdaysAt(words, all, at);
  if (days) {
    return {
      value: {
        rule: () => ({
          ...blank(),
          frequency: "weekly",
          interval,
          weekdays: days.value.map((day) => WEEKDAYS[day].value),
        }),
        rolling: false,
      },
      length: days.length,
    };
  }
  // "every oct 30"
  const yearDay = yearDayAt(words, all, at);
  if (yearDay) return { value: yearly(yearDay.value, interval), length: yearDay.length };
  const unit = unitOf(words, all, at);
  if (!unit) return null;
  const next = at + unit[1];
  // "every month on the 15th", "every 2 months on the last friday"
  if (unit[0] === "month") {
    const skip = filler(words, all, next);
    const day = inMonthAt(words, all, next + skip, interval, true);
    if (day) return { value: day.value, length: unit[1] + skip + day.length };
  }
  // "every year on oct 30"
  if (unit[0] === "year") {
    const skip = filler(words, all, next);
    const day = yearDayAt(words, all, next + skip);
    if (day) return { value: yearly(day.value, interval), length: unit[1] + skip + day.length };
  }
  const preset = PRESET_OF[unit[0]];
  return {
    value: {
      rule: (start) => {
        const rule = createRecurrenceFromPreset(preset, start.toISOString()) ?? blank();
        return { ...rule, interval };
      },
      rolling: false,
      counted: { ...blank(), frequency: FREQUENCY_OF[unit[0]], interval },
    },
    length: unit[1],
  };
};

/** A repeat starting at `at`, with how it ends if the title says. */
const repeatAt = (
  words: TitleWords,
  all: Word[],
  at: number,
  today: Date,
  weekStartsOn: number
): Found<Repeat> | null => {
  let found: Found<Repeat> | null = null;
  const every = phrase(all, at, words.every);
  if (every) {
    let next = at + every;
    let interval = 1;
    // A place before a unit is how often ("every second week", "every third
    // day"), unless a month phrase makes it a day of the month ("every third
    // day of the month"). A place is read before "other": German's "zweiten"
    // is both.
    const position = positionAt(words, all, next);
    const other = position ? 0 : phrase(all, next, words.other);
    const count = all[next]?.core.match(/^(\d{1,3})$/);
    const counted =
      count && (unitOf(words, all, next + 1) || phrase(all, next + 1, words.hour) > 0);
    const often =
      position && position.value !== "last" ? unitOf(words, all, next + position.length) : null;
    const dayOfMonth =
      often?.[0] === "day" &&
      monthPhrase(words, all, next + (position?.length ?? 0) + often[1], true) > 0;
    if (other) {
      interval = 2;
      next += other;
    } else if (count && counted) {
      interval = Number(count[1]);
      next += 1;
    } else if (position && often && !dayOfMonth && position.value !== "last") {
      interval = POSITIONS.indexOf(position.value) + 1;
      next += position.length;
    }
    if (interval < 1 || interval > MAX_INTERVAL) return null;
    const said = everyAt(words, all, next, interval);
    if (said) {
      const length = next - at + said.length;
      // "every! 2 weeks": two weeks from when each one is done.
      const afterDone = all[at + every - 1].bang;
      const counted = said.value.counted;
      found = {
        value: !afterDone
          ? said.value
          : { rule: counted ? () => counted : said.value.rule, rolling: true },
        length: length + monthPhrase(words, all, at + length, true),
      };
    }
  } else {
    // "the last friday of every month", "on the 1st and 15th of each month"
    const skip = filler(words, all, at);
    const said = inMonthAt(words, all, at + skip, 1, true);
    const month = said ? monthPhrase(words, all, at + skip + said.length, false) : 0;
    if (said && month) found = { value: said.value, length: skip + said.length + month };
  }
  if (!found) return null;

  // "until december 1", "10 times"
  let next = at + found.length;
  const until = phrase(all, next, words.until);
  const ends = until ? dateAt(words, all, next + until, today, weekStartsOn, true) : null;
  if (ends) {
    const rule = found.value.rule;
    const end = format(ends.value, "yyyy-MM-dd");
    return {
      value: {
        ...found.value,
        rule: (start) => ({ ...rule(start), ends: "on_date", end_date: end }),
      },
      length: found.length + until + ends.length,
    };
  }
  const times = all[next]?.core.match(/^(\d{1,5})$/);
  const timesWord = times ? phrase(all, next + 1, words.times) : 0;
  if (times && timesWord && Number(times[1]) >= 1 && Number(times[1]) <= MAX_COUNT) {
    const rule = found.value.rule;
    const count = Number(times[1]);
    next += 1 + timesWord;
    return {
      value: {
        ...found.value,
        rule: (start) => ({
          ...rule(start),
          ends: "after_occurrences",
          end_after_occurrences: count,
        }),
      },
      length: next - at,
    };
  }
  return found;
};

const daysIn = (date: Date) => new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();

/** Whether `rule` falls on `date`. */
const fallsOn = (rule: RecurrenceRule, date: Date): boolean => {
  const weekday = WEEKDAYS[weekdayIndex(date)].value;
  const day = date.getDate();
  const last = daysIn(date);
  switch (rule.frequency) {
    case "hourly":
    case "daily":
      return true;
    case "weekly":
      return rule.weekdays.length === 0 || rule.weekdays.includes(weekday);
    case "monthly":
    case "yearly": {
      if (rule.frequency === "yearly" && rule.months.length) {
        if (!rule.months.includes(date.getMonth() + 1)) return false;
      }
      if (rule.monthly_mode === "weekday") {
        if (weekday !== rule.weekday || !rule.weekday_position) return false;
        return rule.weekday_position === "last"
          ? day + 7 > last
          : Math.ceil(day / 7) === POSITIONS.indexOf(rule.weekday_position) + 1;
      }
      if (rule.monthly_mode === "set") {
        if (!rule.weekdays.includes(weekday)) return false;
        const others =
          rule.set_position === "first"
            ? Array.from({ length: day - 1 }, (_, index) => index + 1)
            : Array.from({ length: last - day }, (_, index) => day + 1 + index);
        return !others.some((other) =>
          rule.weekdays.includes(
            WEEKDAYS[weekdayIndex(new Date(date.getFullYear(), date.getMonth(), other))].value
          )
        );
      }
      // A day a short month lacks falls on its last day, as the rule is written.
      return rule.month_days.some(
        (each) => each === day || (each === -1 && day === last) || (each > last && day === last)
      );
    }
  }
};

/** The first day from `today` a repeat falls on, within a few years. */
const firstDay = (repeat: Repeat, today: Date): Date => {
  for (let ahead = 0; ahead < 366 * 5; ahead++) {
    const day = addDays(today, ahead);
    if (fallsOn(repeat.rule(day), day)) return day;
  }
  return today;
};

// ── Tags and people ─────────────────────────────────────────────────────────

/** A tag's name as `#` may spell it: spaces as hyphens or underscores, or none. */
const tagSpellings = (tag: TagSummary): string[] => {
  const base = normalizeWord(tag.name).trim().replace(/\s+/g, " ");
  return [
    ...new Set([base, base.replace(/ /g, "-"), base.replace(/ /g, "_"), base.replace(/ /g, "")]),
  ];
};

/** The tag `#` names at `start`, by its name written out ("#bug fix") or
 *  joined ("#bug-fix"); the longest name that fits wins. */
const tagAt = (
  text: string,
  start: number,
  tags: TagSummary[]
): { tag: TagSummary; end: number } | null => {
  if (text[start] !== "#") return null;
  const rest = normalizeWord(text.slice(start + 1));
  let best: { tag: TagSummary; end: number } | null = null;
  for (const tag of tags) {
    for (const spelling of tagSpellings(tag)) {
      if (!spelling || !rest.startsWith(spelling)) continue;
      // It must end where a word does.
      const after = rest[spelling.length];
      if (after !== undefined && !/[\s.,;:!?)\]]/.test(after)) continue;
      const end = start + 1 + spelling.length;
      if (!best || end > best.end) best = { tag, end };
    }
  }
  return best;
};

/** The handles a title names with `@`, as typed, for looking the people up. */
export const handlesIn = (text: string): string[] =>
  [...new Set([...text.matchAll(/(?:^|\s)@([\p{L}\p{N}_.-]+(?:#\d{1,4})?)/gu)].map((m) => m[1]))]
    .map((handle) => handle.replace(TRAILING, ""))
    .filter((handle) => handle.length > 0);

const personAt = (
  word: string,
  people: TitlePerson[],
  me: TitlePerson | null,
  words: TitleWords
): TitlePerson | null => {
  if (!word.startsWith("@") || word.length < 2) return null;
  const handle = word.slice(1);
  if (me && words.me.includes(handle)) return me;
  const [username, number] = handle.split("#");
  const named = people.filter((person) => normalizeWord(person.username) === username);
  if (number !== undefined) {
    return named.find((person) => person.discriminator === Number(number)) ?? null;
  }
  // Two people of one name are told apart by their number.
  return named.length === 1 ? named[0] : null;
};

// ── Task types ──────────────────────────────────────────────────────────────

/** A name as it is compared, its spaces as one. */
const typeName = (value: string) => normalizeWord(value).trim().replace(/\s+/g, " ");

/** A name as written, but for its case and its spaces. */
const exactTypeName = (value: string) => value.toLowerCase().trim().replace(/\s+/g, " ");

/** The task type a title starts with, named in full and followed straight
 *  away by a colon ("bug:", "user story:"), and where the colon ends. A name
 *  written as a type spells it is that type; one that matches only without its
 *  accents names a type when it names just one. */
const typeAt = (
  text: string,
  types: TaskTypeRead[]
): { type: TaskTypeRead; end: number } | null => {
  const match = text.match(/^\s*([^\s:][^:]*):(?=\s|$)/);
  if (!match || /\s$/.test(match[1])) return null;
  const written = exactTypeName(match[1]);
  const said = typeName(match[1]);
  const loose = types.filter((each) => typeName(each.name) === said);
  const type =
    types.find((each) => exactTypeName(each.name) === written) ??
    (loose.length === 1 ? loose[0] : undefined);
  return type ? { type, end: match[0].length } : null;
};

// ── Reading ─────────────────────────────────────────────────────────────────

/** The end of the day a date without a time is due: done any time that day. */
const endOfDayDue = (date: Date) =>
  set(date, { hours: 23, minutes: 59, seconds: 0, milliseconds: 0 });

/** The title left once `parts` are taken out of `text`. */
const without = (text: string, parts: TitlePart[]): string => {
  let out = "";
  let from = 0;
  for (const part of parts) {
    out += `${text.slice(from, part.start)} `;
    from = part.end;
  }
  out += text.slice(from);
  return out
    .replace(/\s+/g, " ")
    .replace(/\s+([.,;:!?)])/g, "$1")
    .replace(/(^|\s)[.,;:]+(?=\s|$)/g, "$1")
    .replace(/[\s,;:]+$/, "")
    .replace(/^[\s,;:]+/, "")
    .trim();
};

/**
 * What `text` says. The type it starts with, and the first date, time,
 * priority and repeat count; every tag and person does. A part `context.kept` names stays in the title. A title
 * that would be left with nothing keeps all of it, so "Tomorrow" alone is a
 * task called "Tomorrow".
 */
export const readTitle = (text: string, context: TitleContext): TitleReading => {
  const { words, weekStartsOn, kept } = context;
  const today = startOfDay(context.now);
  const all = wordsOf(text);
  const parts: TitlePart[] = [];
  const reading = asTyped(text);
  let date: Date | null = null;
  let time: Time | null = null;
  let repeat: Repeat | null = null;
  // The first word not yet read as part of something.
  let taken = 0;

  const take = (
    type: TitlePartType,
    from: number,
    to: number,
    end?: number,
    id?: number
  ): boolean => {
    const start = all[from].start;
    const stop = end ?? all[to - 1].end;
    const typed = text.slice(start, stop);
    const key = `${type}:${normalizeWord(typed)}`;
    // Kept as typed, and so is any of it: keeping "friday at 5pm" keeps "at 5pm".
    for (const each of kept ?? []) {
      if (each.startsWith(`${type}:`) && each.includes(key.slice(type.length + 1))) return false;
    }
    parts.push({ type, start, end: stop, text: typed, key, ...(id === undefined ? {} : { id }) });
    return true;
  };

  // Only the very start of a title names its type.
  const prefix = typeAt(text, context.types);
  if (prefix) {
    const after = all.findIndex((word) => word.start >= prefix.end);
    const count = after === -1 ? all.length : after;
    if (take("type", 0, count, prefix.end, prefix.type.id)) {
      reading.type = prefix.type;
      taken = count;
    }
  }

  for (let at = taken; at < all.length; at = Math.max(at + 1, taken)) {
    const word = all[at];
    const core = word.core;

    if (core.startsWith("!") && reading.priority === null) {
      const said = core.slice(1);
      const priority =
        ({ "1": "urgent", "2": "high", "3": "medium", "4": "low" } as const)[said] ??
        (Object.keys(words.priorities) as TaskPriority[]).find((each) =>
          words.priorities[each].includes(said)
        );
      if (priority && take("priority", at, at + 1)) {
        reading.priority = priority;
        taken = at + 1;
        continue;
      }
    }

    if (core.startsWith("#")) {
      const found = tagAt(text, word.start, context.tags);
      if (found && !reading.tags.some((tag) => tag.id === found.tag.id)) {
        let to = at + 1;
        while (to < all.length && all[to].start < found.end) to++;
        if (take("tag", at, to, found.end, found.tag.id)) {
          reading.tags.push(found.tag);
          taken = to;
          continue;
        }
      }
    }

    if (core.startsWith("@")) {
      const person = personAt(core, context.people, context.me, words);
      if (person && !reading.people.some((each) => each.id === person.id)) {
        if (take("person", at, at + 1, undefined, person.id)) {
          reading.people.push(person);
          taken = at + 1;
          continue;
        }
      }
    }

    if (repeat === null) {
      const found = repeatAt(words, all, at, today, weekStartsOn);
      if (found && take("repeat", at, at + found.length)) {
        repeat = found.value;
        taken = at + found.length;
        continue;
      }
    }

    if (date === null) {
      // A word that leads a date goes with it ("due friday"), and lets it be
      // shortened ("by fri").
      const lead = phrase(all, at, words.lead);
      const led = lead ? dateAt(words, all, at + lead, today, weekStartsOn, true) : null;
      const own = led ? null : dateAt(words, all, at, today, weekStartsOn, false);
      const hit = led ? { value: led.value, length: lead + led.length } : own;
      if (hit) {
        // A time straight after goes with it: "friday at 5pm".
        const after: Found<Time> | null =
          time === null ? timeAt(words, all, at + hit.length) : null;
        const length = hit.length + (after?.length ?? 0);
        if (take("due", at, at + length)) {
          date = hit.value;
          if (after) time = after.value;
          taken = at + length;
          continue;
        }
      }
    }

    if (time === null) {
      const found = timeAt(words, all, at);
      if (found && take("due", at, at + found.length)) {
        time = found.value;
        taken = at + found.length;
      }
    }
  }

  if (parts.length === 0) return reading;
  const title = without(text, parts);
  if (!title) return asTyped(text);

  const hourly = repeat?.rule(today);
  if (hourly?.frequency === "hourly" && date === null && time === null) {
    // An hourly repeat with no date starts its first count now. Any other
    // repeat, counted from completion or not, starts on the first day it falls on.
    const first = addHours(context.now, hourly.interval);
    date = startOfDay(first);
    time = { hours: first.getHours(), minutes: first.getMinutes() };
  }
  if (repeat !== null && date === null) date = firstDay(repeat, today);
  if (date === null && time !== null) {
    // A time alone is today's, or tomorrow's once today's has gone.
    const todays = set(today, { hours: time.hours, minutes: time.minutes });
    date = todays <= context.now ? addDays(today, 1) : today;
  }
  const due =
    date === null
      ? null
      : time === null
        ? endOfDayDue(date)
        : set(date, { hours: time.hours, minutes: time.minutes, seconds: 0, milliseconds: 0 });

  const valid = due && isValid(due) ? due : null;
  const rule = repeat && valid ? repeat.rule(valid) : null;
  const strategy = repeat?.rolling ? "rolling" : "fixed";
  // What the task form would refuse is not sent: the words stay in the title.
  if (rule && !isValidTaskRecurrence({ rule, strategy, limit: null })) {
    return readTitle(text, {
      ...context,
      kept: new Set([
        ...(kept ?? []),
        ...parts.filter((p) => p.type === "repeat").map((p) => p.key),
      ]),
    });
  }
  return {
    ...reading,
    title,
    parts,
    due: valid,
    dueHasTime: time !== null,
    repeat: rule,
    repeatStrategy: strategy,
  };
};
