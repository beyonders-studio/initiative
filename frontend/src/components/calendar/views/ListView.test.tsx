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
});
