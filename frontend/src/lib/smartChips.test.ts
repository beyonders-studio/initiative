import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SearchEntityType,
  SmartChipAspect,
  SmartChipKind,
  type SmartChipState,
  SmartChipTone,
} from "@/api/generated/initiativeAPI.schemas";
import { CHIP_TONE_CLASSES } from "@/components/editor/editor-ui/chip-tones";
import { nextAsk } from "@/hooks/useSmartChips";
import {
  CHIP_ENTITY_TYPES,
  chipAspect,
  chipDisplay,
  chipEntityType,
  chipKindsFor,
  chipRef,
  isSmartChipKind,
  SMART_CHIP_KINDS,
} from "@/lib/smartChips";

const iso = (date: string) => new Date(date).toISOString();
const formatDate = () => "formatted";

/** A state as the server sends one — every field present. */
const state = (over: Partial<SmartChipState>): SmartChipState => ({
  ref: "task:1:status",
  entity_type: SearchEntityType.task,
  aspect: SmartChipAspect.status,
  text: "",
  title: null,
  tone: SmartChipTone.neutral,
  color: null,
  date: null,
  number: null,
  writable: false,
  ...over,
});

describe("what a smart chip is about", () => {
  it("takes its kinds from the server rather than a list of its own", () => {
    expect(SMART_CHIP_KINDS).toEqual(Object.values(SmartChipKind));
    expect(SMART_CHIP_KINDS).toContain(SmartChipKind["task:status"]);
  });

  it("splits a pair into the thing and the fact", () => {
    expect(chipEntityType(SmartChipKind["task:status"])).toBe(SearchEntityType.task);
    expect(chipAspect(SmartChipKind["task:status"])).toBe("status");
    expect(chipEntityType(SmartChipKind["calendar_event:when"])).toBe(
      SearchEntityType.calendar_event
    );
  });

  it("writes the reference the document stores", () => {
    expect(chipRef(SmartChipKind["task:status"], 12)).toBe("task:12:status");
    expect(chipRef(SmartChipKind["calendar_event:when"], 4)).toBe("calendar_event:4:when");
  });

  it("has a look for every tone the server can send", () => {
    for (const tone of Object.values(SmartChipTone)) {
      expect(CHIP_TONE_CLASSES[tone]).toBeTruthy();
    }
  });

  it("colours from theme tokens, so a chip follows the reader's theme", () => {
    for (const classes of Object.values(CHIP_TONE_CLASSES)) {
      expect(classes).not.toMatch(/\bdark:/);
      // A fixed palette shade would not move with the theme.
      expect(classes).not.toMatch(/-\d{3}\b/);
    }
  });
});

describe("picking a chip in two steps", () => {
  it("names each kind of thing once, however many facts it has", () => {
    expect(CHIP_ENTITY_TYPES).toEqual([...new Set(CHIP_ENTITY_TYPES)]);
    expect(CHIP_ENTITY_TYPES).toContain(SearchEntityType.task);
    expect(CHIP_ENTITY_TYPES).toContain(SearchEntityType.counter);
  });

  it("offers every fact a thing has, and only those", () => {
    // A task is the one with a choice to make; a counter has nothing to ask.
    expect(chipKindsFor(SearchEntityType.task).length).toBeGreaterThan(1);
    expect(chipKindsFor(SearchEntityType.counter)).toEqual([SmartChipKind["counter:value"]]);
    expect(chipKindsFor(SearchEntityType.file)).toEqual([]);
  });

  it("covers every kind between them, so none is unreachable from the toolbar", () => {
    const reachable = CHIP_ENTITY_TYPES.flatMap(chipKindsFor);
    expect(reachable.sort()).toEqual([...SMART_CHIP_KINDS].sort());
  });
});

describe("reading a pair back", () => {
  it("recognises one this build offers", () => {
    expect(isSmartChipKind("task:status")).toBe(true);
  });

  it("refuses one it does not, so a paste cannot make a chip pointing nowhere", () => {
    expect(isSmartChipKind("project:openTasks")).toBe(false);
    expect(isSmartChipKind("")).toBe(false);
  });
});

describe("what a chip shows", () => {
  it("falls back to the stored label when the thing cannot be read", () => {
    const display = chipDisplay("Ship the release", undefined, formatDate, "None");
    expect(display.text).toBe("Ship the release");
    expect(display.className).toBe(CHIP_TONE_CLASSES[SmartChipTone.muted]);
    // The chip is showing words, not a reading — the card behind it says so.
    expect(display.live).toBe(false);
  });

  it("shows the live state over the label the document stored", () => {
    const display = chipDisplay(
      "Ship the release",
      state({ text: "Done", tone: SmartChipTone.good }),
      formatDate,
      "None"
    );
    expect(display.text).toBe("Done");
    expect(display.className).toBe(CHIP_TONE_CLASSES[SmartChipTone.good]);
    expect(display.live).toBe(true);
  });

  it("lets the thing's own colour beat the tone", () => {
    const display = chipDisplay(
      "x",
      state({ text: "Blocked", color: "#FF00AA" }),
      formatDate,
      "None"
    );
    expect(display.color).toBe("#FF00AA");
  });

  it("formats a date in the reader's locale rather than showing the server's", () => {
    const display = chipDisplay(
      "x",
      state({
        ref: "task:1:due",
        aspect: SmartChipAspect.due,
        text: "2026-09-12",
        date: iso("2026-09-12T10:00:00Z"),
      }),
      formatDate,
      "None"
    );
    expect(display.text).toBe("formatted");
  });
});

describe("a chip that was answered with nothing", () => {
  it("says so rather than showing the label beside it", () => {
    // An unassigned task must not render its own title where the person goes.
    const display = chipDisplay(
      "Ship the release",
      state({
        ref: "task:1:assignee",
        aspect: SmartChipAspect.assignee,
        tone: SmartChipTone.muted,
      }),
      formatDate,
      "None"
    );
    expect(display.text).toBe("None");
    // Answered, so the card behind it can still offer to open the task.
    expect(display.live).toBe(true);
  });
});

describe("a chip whose reading turns at a set time", () => {
  const BACKSTOP = 5 * 60_000;
  const now = new Date("2026-10-10T12:00:00Z");
  const dated = (iso: string | null) => state({ ref: "task:1:due", date: iso });

  afterEach(() => vi.useRealTimers());

  it("asks again just after that moment, when it comes before the backstop", () => {
    vi.useFakeTimers({ now });
    expect(nextAsk(dated("2026-10-10T12:02:00Z"))).toBe(2 * 60_000 + 1_000);
  });

  it("waits for the backstop when that moment is further off", () => {
    vi.useFakeTimers({ now });
    expect(nextAsk(dated("2026-10-11T12:00:00Z"))).toBe(BACKSTOP);
  });

  it("waits for the backstop once that moment has passed, or where there is none", () => {
    vi.useFakeTimers({ now });
    expect(nextAsk(dated("2026-10-10T11:00:00Z"))).toBe(BACKSTOP);
    expect(nextAsk(dated(null))).toBe(BACKSTOP);
    expect(nextAsk(undefined)).toBe(BACKSTOP);
  });
});
