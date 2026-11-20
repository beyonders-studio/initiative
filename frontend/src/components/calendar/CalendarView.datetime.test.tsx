import type { DragEndEvent } from "@dnd-kit/core";
import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildCalendarEventSummary } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { toast } from "@/lib/mascotToast";

import { CalendarView } from "./CalendarView";
import { allDayRange, buildEventCalendarEntry } from "./eventCalendarEntry";
import { DayColumn } from "./views/shared";

const drag = vi.hoisted(() => ({
  finish: (event: DragEndEvent) => {
    void event;
  },
}));
vi.mock("@dnd-kit/core", async (importOriginal) => {
  const original = await importOriginal<typeof import("@dnd-kit/core")>();
  return {
    ...original,
    DndContext: ({ children, onDragEnd }: React.ComponentProps<typeof original.DndContext>) => {
      drag.finish = (event) => onDragEnd?.(event);
      return <div>{children}</div>;
    },
  };
});

describe("calendar date rescheduling", () => {
  it("ends a midnight-gap day at the next midnight rather than the next 01:00", () => {
    vi.stubEnv("TZ", "America/Sao_Paulo");
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        title: "Tomorrow's event",
        start_at: "2018-11-05T00:30:00-02:00",
        end_at: "2018-11-05T00:45:00-02:00",
      }),
      undefined,
      false
    );
    renderWithProviders(<DayColumn day={new Date("2018-11-04T12:00:00")} entries={[entry]} />);
    expect(screen.queryByRole("button", { name: /tomorrow's event/i })).not.toBeInTheDocument();
  });

  it.each(["2026-03-29", "2026-10-25"])("refuses a skipped or repeated hour slot on %s", (day) => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const selected = vi.fn();
    const error = vi.spyOn(toast, "error").mockImplementation(() => {});
    renderWithProviders(
      <DayColumn day={new Date(`${day}T12:00:00`)} entries={[]} onSlotClick={selected} />
    );
    const slot = screen.getAllByRole("button")[2];
    if (!slot) throw new Error("Missing 02:00 slot");
    fireEvent.click(slot);
    expect(selected).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalledWith(expect.stringMatching(/skipped or repeated/i));
  });

  it("gives overlapping fold markers separate visible lanes", () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const entries = ["First fold marker", "Second fold marker"].map((title, index) =>
      buildEventCalendarEntry(
        buildCalendarEventSummary({
          id: index + 1,
          title,
          start_at: "2026-10-25T02:30:00+02:00",
          end_at: "2026-10-25T02:15:00+01:00",
        }),
        undefined,
        false
      )
    );
    renderWithProviders(<DayColumn day={new Date("2026-10-25T12:00:00")} entries={entries} />);
    const first = screen.getByRole("button", { name: /first fold marker/i });
    const second = screen.getByRole("button", { name: /second fold marker/i });
    expect(first).toHaveStyle({ top: "100px", height: "20px" });
    expect(second).toHaveStyle({ top: "100px", height: "20px" });
    expect(first.style.left).not.toBe(second.style.left);
  });

  it.each(["year", "list"])(
    "keeps the last visible date after a midnight gap in %s view",
    (view) => {
      vi.stubEnv("TZ", "America/Sao_Paulo");
      const entry = buildEventCalendarEntry(
        buildCalendarEventSummary({
          all_day: true,
          title: "Midnight gap span",
          start_at: "2018-01-01T00:00:00Z",
          end_at: view === "year" ? "2018-12-31T23:59:59Z" : "2018-11-30T23:59:59Z",
        }),
        undefined,
        false
      );
      const { container } = renderWithProviders(
        <CalendarView
          entries={[entry]}
          viewMode={view === "year" ? "year" : "list"}
          onViewModeChange={vi.fn()}
          focusDate={new Date(2018, 10, 1)}
          onFocusDateChange={vi.fn()}
        />
      );
      if (view === "year")
        expect(container.querySelectorAll("button:not(:disabled) span.rounded-full")).toHaveLength(
          365
        );
      else expect(screen.getAllByRole("button", { name: /midnight gap span/i })).toHaveLength(30);
    }
  );

  it.each([
    ["2026-03-28", "2026-03-29", "Europe/Amsterdam"],
    ["2026-10-25", "2026-10-26", "Europe/Amsterdam"],
    ["2018-11-03", "2018-11-04", "America/Sao_Paulo"],
  ])("keeps an all-day event one calendar day when moved %s to %s", (from, to, zone) => {
    vi.stubEnv("TZ", zone);
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        all_day: true,
        start_at: `${from}T00:00:00Z`,
        end_at: `${from}T23:59:59Z`,
      }),
      undefined,
      false
    );
    const saved = vi.fn();
    renderWithProviders(
      <CalendarView
        entries={[entry]}
        viewMode="month"
        onViewModeChange={vi.fn()}
        focusDate={new Date(`${from}T12:00:00`)}
        onFocusDateChange={vi.fn()}
        onEntryReschedule={({ startAt, endAt }) => saved(allDayRange(startAt, endAt))}
      />
    );
    act(() =>
      drag.finish({
        active: {
          id: entry.id,
          data: { current: { entry } },
          rect: { current: { initial: null, translated: null } },
        },
        over: {
          disabled: false,
          id: to,
          data: { current: { type: "day", dateKey: to } },
          rect: { top: 0, left: 0, bottom: 40, right: 40, width: 40, height: 40 },
        },
        activatorEvent: new MouseEvent("pointerup"),
        collisions: null,
        delta: { x: 0, y: 0 },
      })
    );
    expect(saved).toHaveBeenCalledWith({ start_at: `${to}T00:00:00Z`, end_at: `${to}T23:59:59Z` });
  });

  it("labels an imported backwards-clock span without inventing a one-hour block", () => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        title: "Fold span",
        start_at: "2026-10-25T02:30:00+02:00",
        end_at: "2026-10-25T02:15:00+01:00",
      }),
      undefined,
      false
    );
    renderWithProviders(
      <CalendarView
        entries={[entry]}
        viewMode="day"
        onViewModeChange={vi.fn()}
        focusDate={new Date("2026-10-25T12:00:00")}
        onFocusDateChange={vi.fn()}
      />
    );
    const block = screen.getByRole("button", { name: /fold span/i });
    expect(block).toHaveStyle({ top: "100px", height: "20px" });
    expect(block).toHaveTextContent(/2:30\s*am \([+]02:00\).*2:15\s*am \([+]01:00\)/i);
    expect(block).toHaveAttribute("title", expect.stringContaining("+01:00"));
  });

  it("renders a long event on every day of its visible year", () => {
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        title: "Year event",
        all_day: true,
        start_at: "2026-01-01T00:00:00Z",
        end_at: "2026-12-31T23:59:59Z",
      }),
      undefined,
      false
    );
    const { container } = renderWithProviders(
      <CalendarView
        entries={[entry]}
        viewMode="year"
        onViewModeChange={vi.fn()}
        focusDate={new Date(2026, 5, 1)}
        onFocusDateChange={vi.fn()}
      />
    );
    expect(container.querySelectorAll("button:not(:disabled) span.rounded-full")).toHaveLength(365);
  });

  it("clips long list spans to the focus month without dropping later days", () => {
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        title: "Long event",
        all_day: true,
        start_at: "2026-01-01T00:00:00Z",
        end_at: "2026-12-31T23:59:59Z",
      }),
      undefined,
      false
    );
    renderWithProviders(
      <CalendarView
        entries={[entry]}
        viewMode="list"
        onViewModeChange={vi.fn()}
        focusDate={new Date(2026, 5, 1)}
        onFocusDateChange={vi.fn()}
      />
    );
    expect(screen.getAllByRole("button", { name: /long event/i })).toHaveLength(30);
  });

  it.each([
    ["2026-03-29", "09:00:00", 360],
    ["2026-10-25", "09:00:00", 360],
  ])("positions %s %s at its wall-clock row", (day, time, expectedTop) => {
    vi.stubEnv("TZ", "Europe/Amsterdam");
    const entry = buildEventCalendarEntry(
      buildCalendarEventSummary({
        title: "Morning event",
        start_at: new Date(`${day}T${time}`).toISOString(),
        end_at: new Date(`${day}T10:00:00`).toISOString(),
      }),
      undefined,
      false
    );
    renderWithProviders(
      <CalendarView
        entries={[entry]}
        viewMode="day"
        onViewModeChange={vi.fn()}
        focusDate={new Date(`${day}T12:00:00`)}
        onFocusDateChange={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: /morning event/i })).toHaveStyle({
      top: `${expectedTop}px`,
    });
  });
});
