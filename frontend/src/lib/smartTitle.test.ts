import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { buildTaskType } from "@/__tests__/factories";
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { HINTS } from "@/components/tasks/SmartTitleHints";
import { fromStored, isValidTaskRecurrence, shiftFor, toRRule } from "@/lib/recurrence";

import {
  handlesIn,
  readTitle,
  type TitleContext,
  type TitlePerson,
  titleWords,
} from "./smartTitle";

const catalogue = (locale: string) =>
  JSON.parse(
    fs.readFileSync(path.resolve(__dirname, `../../public/locales/${locale}/tasks.json`), "utf-8")
  );

const wordsFor = (locale: string) => {
  const { smartTitle, priority } = catalogue(locale);
  return titleWords(smartTitle.words, priority, locale);
};

const EN = wordsFor("en");

// Thursday 22 October 2026, ten in the morning.
const NOW = new Date(2026, 9, 22, 10, 0);

const tag = (id: number, name: string): TagSummary => ({ id, name, color: "#6366F1" });
const person = (id: number, username: string, discriminator = 1): TitlePerson => ({
  id,
  username,
  discriminator,
  display_name: null,
  avatar_url: null,
  status: "active",
});

const ME = person(1, "jordan");
const SAM = person(2, "sam");

const BUG = buildTaskType({ id: 30, name: "Bug" });
const STORY = buildTaskType({ id: 31, name: "User story" });
const MILESTONE = buildTaskType({ id: 32, name: "Étape" });

const context = (overrides: Partial<TitleContext> = {}): TitleContext => ({
  now: NOW,
  words: EN,
  weekStartsOn: 1,
  tags: [tag(10, "billing"), tag(11, "Bug fix"), tag(12, "bug")],
  types: [BUG, STORY, MILESTONE],
  people: [SAM],
  me: ME,
  ...overrides,
});

const read = (text: string, overrides?: Partial<TitleContext>) =>
  readTitle(text, context(overrides));

/** The due date as a local "yyyy-mm-dd hh:mm", which is how the tests say it. */
const due = (text: string, overrides?: Partial<TitleContext>) => {
  const date = read(text, overrides).due;
  if (!date) return null;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

describe("readTitle — dates", () => {
  it("reads today and tomorrow, due at the end of the day", () => {
    expect(read("Call the bank today").title).toBe("Call the bank");
    expect(due("Call the bank today")).toBe("2026-10-22 23:59");
    expect(due("Call the bank tomorrow")).toBe("2026-10-23 23:59");
    expect(read("Call the bank tomorrow").dueHasTime).toBe(false);
  });

  it("reads a weekday as the coming one, today included", () => {
    expect(due("Report friday")).toBe("2026-10-23 23:59");
    expect(due("Report thursday")).toBe("2026-10-22 23:59");
    expect(due("Report wednesday")).toBe("2026-10-28 23:59");
    expect(due("Report monday")).toBe("2026-10-26 23:59");
  });

  it("reads next weekday as that day of next week", () => {
    expect(due("Report next friday")).toBe("2026-10-30 23:59");
    expect(due("Report next monday")).toBe("2026-10-26 23:59");
    // A week starting on Sunday puts next Monday in the same place.
    expect(due("Report next monday", { weekStartsOn: 0 })).toBe("2026-10-26 23:59");
  });

  it("reads a shortened weekday only after a word that leads a date", () => {
    expect(due("Report by fri")).toBe("2026-10-23 23:59");
    expect(read("Report by fri").title).toBe("Report");
    expect(due("Sit in the sun")).toBeNull();
    expect(read("Sit in the sun").title).toBe("Sit in the sun");
  });

  it("reads next week, month and year as where they start", () => {
    expect(due("Plan next week")).toBe("2026-10-26 23:59");
    expect(due("Plan next week", { weekStartsOn: 0 })).toBe("2026-10-25 23:59");
    expect(due("Plan next month")).toBe("2026-11-01 23:59");
    expect(due("Plan next year")).toBe("2027-01-01 23:59");
  });

  it("reads in a count of units", () => {
    expect(due("Renew in 3 days")).toBe("2026-10-25 23:59");
    expect(due("Renew in a week")).toBe("2026-10-29 23:59");
    expect(due("Renew in 2 months")).toBe("2026-12-22 23:59");
    expect(read("Put 5 in 2 boxes").parts).toEqual([]);
  });

  it("reads a month and day either way round, rolling past dates to next year", () => {
    expect(due("Party oct 30")).toBe("2026-10-30 23:59");
    expect(due("Party 30th of October")).toBe("2026-10-30 23:59");
    expect(due("Party on 3 march")).toBe("2027-03-03 23:59");
    expect(due("Party October 30 2027")).toBe("2027-10-30 23:59");
    expect(due("Party 2026-12-01")).toBe("2026-12-01 23:59");
    expect(due("Party feb 30")).toBeNull();
  });

  it("leaves a month without a day alone", () => {
    expect(read("Write the March report").parts).toEqual([]);
  });

  it("reads only the first date", () => {
    const reading = read("Move today's thing to friday or monday");
    expect(reading.title).toBe("Move today's thing to or monday");
    expect(due("Move today's thing to friday or monday")).toBe("2026-10-23 23:59");
  });
});

describe("readTitle — times", () => {
  it("reads a time after a date", () => {
    expect(due("Standup tomorrow at 9am")).toBe("2026-10-23 09:00");
    expect(due("Standup friday 5:30pm")).toBe("2026-10-23 17:30");
    expect(due("Standup friday at 17:00")).toBe("2026-10-23 17:00");
    expect(read("Standup friday at 17:00").title).toBe("Standup");
    expect(read("Standup friday at 17:00").dueHasTime).toBe(true);
  });

  it("reads a time anywhere, before the date too", () => {
    expect(due("At 3pm call Sam on friday")).toBe("2026-10-23 15:00");
    expect(read("At 3pm call Sam on friday").title).toBe("call Sam");
  });

  it("puts a time alone today, or tomorrow once today's has gone", () => {
    expect(due("Stretch at 4pm")).toBe("2026-10-22 16:00");
    expect(due("Stretch at 8am")).toBe("2026-10-23 08:00");
    expect(due("Stretch at noon")).toBe("2026-10-22 12:00");
    expect(due("Stretch 9 p.m.")).toBe("2026-10-22 21:00");
  });

  it("leaves a bare number alone unless it is led by at", () => {
    expect(read("Read chapter 5").parts).toEqual([]);
    expect(due("Meet at 14")).toBe("2026-10-22 14:00");
    expect(read("Buy 13pm things").parts).toEqual([]);
  });
});

describe("readTitle — priority", () => {
  it("reads a priority by name or number", () => {
    expect(read("Fix login !high").priority).toBe("high");
    expect(read("Fix login !high").title).toBe("Fix login");
    expect(read("Fix login !Urgent").priority).toBe("urgent");
    expect(read("Fix login !1").priority).toBe("urgent");
    expect(read("Fix login !4").priority).toBe("low");
  });

  it("leaves an exclamation that names no priority alone", () => {
    expect(read("Ship it !").parts).toEqual([]);
    expect(read("Ship !now").parts).toEqual([]);
  });
});

describe("readTitle — tags and people", () => {
  it("reads every tag the community has", () => {
    const reading = read("Invoice #billing #bug");
    expect(reading.tags.map((each) => each.id)).toEqual([10, 12]);
    expect(reading.title).toBe("Invoice");
  });

  it("reads a tag of several words written out or joined, the longest first", () => {
    expect(read("Login #bug fix").tags.map((each) => each.id)).toEqual([11]);
    expect(read("Login #bug-fix").tags.map((each) => each.id)).toEqual([11]);
    expect(read("Login #bug_fix please").title).toBe("Login please");
    expect(read("Login #bugs").parts).toEqual([]);
  });

  it("leaves a tag the community does not have", () => {
    expect(read("Login #nope").parts).toEqual([]);
  });

  it("reads people by handle, and me", () => {
    const reading = read("Review @sam @me");
    expect(reading.people.map((each) => each.id)).toEqual([2, 1]);
    expect(reading.title).toBe("Review");
  });

  it("tells two people of one name apart only by their number", () => {
    const people = [person(2, "sam", 1), person(3, "sam", 42)];
    expect(read("Review @sam", { people }).people).toEqual([]);
    expect(read("Review @sam#0042", { people }).people.map((each) => each.id)).toEqual([3]);
  });

  it("lists the handles a title names, for looking them up", () => {
    expect(handlesIn("Ask @sam and @alex.b, cc @sam#0042 but not a@b.c")).toEqual([
      "sam",
      "alex.b",
      "sam#0042",
    ]);
  });
});

describe("readTitle — task types", () => {
  it("reads the type a title starts with, by its whole name", () => {
    const reading = read("Bug: login broken");
    expect(reading.type?.id).toBe(BUG.id);
    expect(reading.title).toBe("login broken");
    expect(reading.parts).toEqual([
      { type: "type", start: 0, end: 4, text: "Bug:", key: "type:bug:", id: BUG.id },
    ]);
  });

  it("reads a name of several words, whatever its case and accents", () => {
    expect(read("user  STORY: Sign in with a passkey").type?.id).toBe(STORY.id);
    expect(read("etape: Ship v2 friday").type?.id).toBe(MILESTONE.id);
    expect(read("etape: Ship v2 friday").title).toBe("Ship v2");
    expect(read("  bug: spaced in").title).toBe("spaced in");
  });

  it("reads it only at the very start, straight before a colon", () => {
    expect(read("Fix bug: login").type).toBeNull();
    expect(read("bug : login").type).toBeNull();
    expect(read("bug:login").type).toBeNull();
    expect(read("Meeting at 15:00").type).toBeNull();
    expect(read("Bug report: draft").type).toBeNull();
  });

  it("leaves a name the project has no type of, and a type with nothing after it", () => {
    expect(read("Note: buy milk").title).toBe("Note: buy milk");
    const alone = read("bug:");
    expect(alone.type).toBeNull();
    expect(alone.title).toBe("bug:");
  });

  it("reads the rest of the title after it", () => {
    const reading = read("bug: login broken tomorrow !high #billing");
    expect(reading.type?.id).toBe(BUG.id);
    expect(reading.priority).toBe("high");
    expect(reading.tags.map((each) => each.id)).toEqual([10]);
    expect(reading.title).toBe("login broken");
  });

  it("keeps a type kept as typed", () => {
    const kept = new Set(read("bug: login").parts.map((part) => part.key));
    const reading = read("bug: login", { kept });
    expect(reading.type).toBeNull();
    expect(reading.title).toBe("bug: login");
  });
});

describe("the hints' examples", () => {
  for (const locale of ["en", "de", "es", "fr"]) {
    it(`reads every example the ${locale} hints give`, () => {
      const { smartTitle } = catalogue(locale);
      const examples = (key: string) => (smartTitle.hints[key].examples as string).split("|");
      const words = wordsFor(locale);
      const tags = examples("tags").map((each, index) => tag(100 + index, each.slice(1)));
      const types = examples("type").map((each, index) =>
        buildTaskType({ id: 200 + index, name: each.slice(0, -1) })
      );
      for (const { key, type } of HINTS) {
        for (const example of examples(key)) {
          const text = type === "type" ? `${example} Task` : `Task ${example}`;
          const reading = read(text, { words, tags, types });
          expect(
            reading.parts.map((part) => part.type),
            `${locale} ${key}: ${example}`
          ).toEqual([type]);
          expect(reading.title, `${locale} ${key}: ${example}`).toBe("Task");
        }
      }
    });
  }
});

describe("readTitle — repeats", () => {
  it("reads every unit, from today when no date is given", () => {
    const reading = read("Water plants every day");
    expect(reading.title).toBe("Water plants");
    expect(reading.repeat && toRRule(reading.repeat)).toBe("RRULE:FREQ=DAILY");
    expect(due("Water plants every day")).toBe("2026-10-22 23:59");
  });

  it("reads a weekday, starting on the coming one", () => {
    const reading = read("Bins every monday at 7am");
    expect(reading.repeat && toRRule(reading.repeat)).toBe("RRULE:FREQ=WEEKLY;BYDAY=MO");
    expect(due("Bins every monday at 7am")).toBe("2026-10-26 07:00");
    expect(reading.title).toBe("Bins");
  });

  it("reads intervals", () => {
    const other = read("Payroll every other week").repeat;
    expect(other && toRRule(other)).toBe("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TH");
    const three = read("Rotate keys every 3 months").repeat;
    expect(three && toRRule(three)).toBe("RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=22");
  });

  it("starts a weekly repeat on the date it is given", () => {
    const reading = read("Sync every week starting friday");
    expect(reading.repeat && toRRule(reading.repeat)).toBe("RRULE:FREQ=WEEKLY;BYDAY=FR");
  });

  it("reads every weekday, from Monday when today is a weekend", () => {
    const reading = read("Inbox every weekday", { now: new Date(2026, 9, 24, 10) });
    expect(reading.repeat && toRRule(reading.repeat)).toBe(
      "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    );
    expect(due("Inbox every weekday", { now: new Date(2026, 9, 24, 10) })).toBe("2026-10-26 23:59");
  });
});

describe("readTitle — repeats counted from completion", () => {
  it("starts an hourly repeat its interval from now", () => {
    expect(due("Meds every 4 hours")).toBe("2026-10-22 14:00");
  });

  it("starts any other on the first day it falls on, not hours from now", () => {
    expect(due("Mow the lawn every! 2 weeks")).toBe("2026-10-22 23:59");
    expect(due("Call home every! sunday")).toBe("2026-10-25 23:59");
    expect(read("Call home every! sunday").dueHasTime).toBe(false);
  });
});

describe("readTitle — what stays", () => {
  it("reads it all at once", () => {
    const reading = read("Send the invoice friday at 3pm !high #billing @sam");
    expect(reading.title).toBe("Send the invoice");
    expect(reading.priority).toBe("high");
    expect(reading.tags.map((each) => each.id)).toEqual([10]);
    expect(reading.people.map((each) => each.id)).toEqual([2]);
    expect(due("Send the invoice friday at 3pm !high #billing @sam")).toBe("2026-10-23 15:00");
    expect(reading.parts.map((part) => part.text)).toEqual([
      "friday at 3pm",
      "!high",
      "#billing",
      "@sam",
    ]);
  });

  it("tidies the punctuation the parts leave behind", () => {
    expect(read("Call mom tomorrow, then shop").title).toBe("Call mom, then shop");
    expect(read("Call mom (tomorrow)").title).toBe("Call mom ()");
    expect(read("Call mom tomorrow.").title).toBe("Call mom.");
  });

  it("keeps a title that would be left with nothing", () => {
    const reading = read("Tomorrow");
    expect(reading.title).toBe("Tomorrow");
    expect(reading.parts).toEqual([]);
    expect(reading.due).toBeNull();
  });

  it("keeps what is kept as typed, and anything inside it", () => {
    const first = read("Lunch friday at 1pm");
    const kept = new Set(first.parts.map((part) => part.key));
    const reading = read("Lunch friday at 1pm", { kept });
    expect(reading.parts).toEqual([]);
    expect(reading.title).toBe("Lunch friday at 1pm");
  });

  it("marks where each part is in the title", () => {
    const text = "Pay rent tomorrow !high";
    for (const part of read(text).parts) {
      expect(text.slice(part.start, part.end)).toBe(part.text);
    }
  });
});

describe("readTitle — other languages", () => {
  it("reads French, where next comes after", () => {
    const fr = { words: wordsFor("fr") };
    expect(due("Rapport vendredi prochain", fr)).toBe("2026-10-30 23:59");
    expect(due("Rapport demain à 17h30", fr)).toBe("2026-10-23 17:30");
    expect(read("Rapport demain à 17h30", fr).title).toBe("Rapport");
    expect(due("Rapport le 3 novembre", fr)).toBe("2026-11-03 23:59");
    const repeat = read("Arroser tous les jours", fr).repeat;
    expect(repeat && toRRule(repeat)).toBe("RRULE:FREQ=DAILY");
    expect(read("Corriger !haute", fr).priority).toBe("high");
  });

  it("reads German and Spanish", () => {
    const de = { words: wordsFor("de") };
    expect(due("Bericht bis Freitag um 15 Uhr", de)).toBe("2026-10-23 15:00");
    expect(due("Bericht am 30. Oktober", de)).toBe("2026-10-30 23:59");
    expect(due("Bericht in 2 Wochen", de)).toBe("2026-11-05 23:59");
    const es = { words: wordsFor("es") };
    expect(due("Informe el viernes a las 15:00", es)).toBe("2026-10-23 15:00");
    expect(due("Informe dentro de 3 días", es)).toBe("2026-10-25 23:59");
    expect(due("Informe el lunes que viene", es)).toBe("2026-10-26 23:59");
    const repeat = read("Regar todos los lunes", es).repeat;
    expect(repeat && toRRule(repeat)).toBe("RRULE:FREQ=WEEKLY;BYDAY=MO");
  });
});

describe("readTitle — repeats the server takes", () => {
  const fixture = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "smartTitle.repeats.json"), "utf-8")
  ) as {
    now: string;
    weekStartsOn: number;
    cases: {
      locale: string;
      text: string;
      title: string;
      rrule: string | null;
      strategy: "fixed" | "rolling" | null;
      until?: string;
    }[];
  };
  const now = new Date(fixture.now);
  const untilOf = (rrule: string) => rrule.match(/UNTIL=(\d{8}T\d{6}Z)/)?.[1];
  const instant = (stamp: string) =>
    new Date(
      `${stamp.slice(0, 4)}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)}T${stamp.slice(9, 11)}:${stamp.slice(11, 13)}:${stamp.slice(13, 15)}Z`
    );

  it.each(fixture.cases)("$text", (expected) => {
    const reading = readTitle(expected.text, {
      ...context({ now, weekStartsOn: fixture.weekStartsOn, tags: [], people: [] }),
      words: wordsFor(expected.locale),
    });
    expect(reading.title).toBe(expected.title);
    if (expected.rrule === null) {
      expect(reading.repeat).toBeNull();
      return;
    }
    expect(reading.repeat).not.toBeNull();
    const rule = reading.repeat as NonNullable<typeof reading.repeat>;
    const rrule = toRRule(rule);
    // An UNTIL is the end of its day in this zone; the rest is as written.
    const bare = (text: string) => text.replace(/;UNTIL=\d{8}T\d{6}Z/, "");
    expect(bare(rrule)).toBe(bare(expected.rrule));
    if (expected.until) {
      const [y, m, d] = expected.until.split("-").map(Number);
      expect(instant(untilOf(rrule) ?? "")).toEqual(new Date(y, m - 1, d, 23, 59, 59));
    }
    expect(reading.repeatStrategy).toBe(expected.strategy);
    const strategy = reading.repeatStrategy;
    expect(isValidTaskRecurrence({ rule, strategy, limit: null })).toBe(true);

    // The repeat editor reads it back as the same rule, not as one it can't show.
    const due = reading.due as Date;
    const back = fromStored(
      rrule,
      due.toISOString(),
      shiftFor(rule, due),
      false,
      strategy === "rolling"
    );
    expect(back).not.toBe("custom");
    expect(back).not.toBeNull();
    expect(toRRule(back as NonNullable<typeof rule>)).toBe(rrule);
  });
});
