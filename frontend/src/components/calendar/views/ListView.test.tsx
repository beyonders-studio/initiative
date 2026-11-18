import { screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import type { CalendarEntry } from "../CalendarView";
import { ListView } from "./ListView";

const entry: CalendarEntry = {
  id: "event-1",
  title: "Harvest festival",
  startAt: "2026-10-23T00:00:00",
  endAt: "2026-10-23T00:00:00",
  allDay: true,
  meta: { type: "event", eventId: 1 },
};

const german = createInstance();
void german.init({
  lng: "de",
  resources: { de: { common: {} } },
  initAsync: false,
  react: { useSuspense: false },
});

describe("the calendar's list", () => {
  it("names each day's weekday and month in the reader's language (#2911)", async () => {
    renderWithProviders(
      <I18nextProvider i18n={german}>
        <ListView entries={[entry]} focusDate={new Date("2026-10-15T12:00:00")} />
      </I18nextProvider>
    );

    expect(await screen.findByText("Freitag")).toBeInTheDocument();
    expect(screen.getByText(/^Okt/)).toBeInTheDocument();
    expect(screen.queryByText("Friday")).toBeNull();
  });

  it("says when an event running past midnight stops, not that it fills the day", async () => {
    const lateNight: CalendarEntry = {
      id: "event-2",
      title: "Open game night",
      startAt: "2026-10-23T20:00:00",
      endAt: "2026-10-24T00:30:00",
      allDay: false,
      meta: { type: "event", eventId: 2 },
    };
    renderWithProviders(
      <ListView entries={[lateNight]} focusDate={new Date("2026-10-15T12:00:00")} />
    );

    expect(await screen.findAllByRole("button")).toHaveLength(2);
    expect(screen.getByText(/^Until /)).toBeInTheDocument();
    expect(screen.queryByText("All day")).toBeNull();
  });

  it("keeps an event that ends at midnight on the day it started", async () => {
    const evening: CalendarEntry = {
      id: "event-3",
      title: "Painting night",
      startAt: "2026-10-23T18:00:00",
      endAt: "2026-10-24T00:00:00",
      allDay: false,
      meta: { type: "event", eventId: 3 },
    };
    renderWithProviders(
      <ListView entries={[evening]} focusDate={new Date("2026-10-15T12:00:00")} />
    );

    expect(await screen.findAllByRole("button")).toHaveLength(1);
    expect(screen.queryByText(/^Until /)).toBeNull();
  });

  it("calls a day the event runs to its midnight 'All day'", async () => {
    const weekend: CalendarEntry = {
      id: "event-4",
      title: "Weekend retreat",
      startAt: "2026-10-23T18:00:00",
      endAt: "2026-10-25T00:00:00",
      allDay: false,
      meta: { type: "event", eventId: 4 },
    };
    renderWithProviders(
      <ListView entries={[weekend]} focusDate={new Date("2026-10-15T12:00:00")} />
    );

    expect(await screen.findAllByRole("button")).toHaveLength(2);
    expect(screen.getByText("All day")).toBeInTheDocument();
    expect(screen.queryByText(/^Until /)).toBeNull();
  });
});
