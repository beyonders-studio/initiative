/**
 * What the Repeat field says, and the dates it shows.
 *
 * The summary line under the preset select restated the select's own value:
 * an untouched form read "Does not repeat" twice over. It now appears only
 * once there is a real rule for it to describe, with the next dates from the
 * server beneath it.
 */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { RecurrenceEditor } from "@/ui/recurrence/RecurrenceEditor";
import {
  createRecurrenceFromPreset,
  fromStored,
  type RecurrenceRule,
  type TaskRecurrenceValue,
} from "@/ui/recurrence/recurrence";

const renderEditor = (value: RecurrenceRule | "custom" | null, referenceDate?: string) =>
  renderWithProviders(
    <RecurrenceEditor
      kind="event"
      value={value}
      onChange={() => {}}
      referenceDate={referenceDate ?? null}
      allDay
      stored={value === "custom" ? { rule: "RRULE:FREQ=HOURLY", shift: 0 } : null}
    />
  );

describe("RecurrenceEditor", () => {
  it("says 'Does not repeat' once, in the select, when there is no rule", async () => {
    renderEditor(null);

    // The select still carries the label; what is gone is the paragraph under
    // it that used to repeat the same words.
    expect(await screen.findAllByText(/does not repeat/i)).toHaveLength(1);
  });

  it("summarises a real rule beneath the select", async () => {
    renderEditor({
      ...(createRecurrenceFromPreset("daily") as RecurrenceRule),
      frequency: "weekly",
      interval: 2,
      weekdays: ["monday"],
    });

    expect(await screen.findByText(/every 2 weeks/i)).toBeInTheDocument();
    expect(screen.queryByText(/does not repeat/i)).not.toBeInTheDocument();
  });

  it("shows the next dates the server gives, for a rule it can't build too", async () => {
    let asked: Record<string, unknown> | undefined;
    server.use(
      http.post("/api/v1/recurrence/preview", async ({ request }) => {
        asked = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          rule: asked.rule,
          shift: 0,
          occurrences: ["2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z"],
        });
      })
    );
    renderEditor("custom", "2026-10-05T09:00:00");

    expect(await screen.findByText(/oct 5, 2026 · oct 6, 2026/i)).toBeInTheDocument();
    // The stored rule, with its own shift, from the all-day event's date.
    expect(asked).toMatchObject({
      rule: "RRULE:FREQ=HOURLY",
      shift: 0,
      start: "2026-10-05T00:00:00Z",
    });
  });
});

const HourlyEditor = ({
  hasDueDate = true,
  initialLimit = 3,
}: {
  hasDueDate?: boolean;
  initialLimit?: number | null;
}) => {
  const [repeat, setRepeat] = useState<TaskRecurrenceValue>({
    rule: fromStored("RRULE:FREQ=HOURLY;INTERVAL=4", "2026-10-05T08:00:00", 0, false, true),
    strategy: "rolling",
    limit: initialLimit,
  });
  return (
    <form>
      <RecurrenceEditor
        kind="task"
        value={repeat.rule}
        onChange={() => {}}
        strategy={repeat.strategy}
        limit={repeat.limit}
        onTaskChange={setRepeat}
        referenceDate="2026-10-05T08:00:00"
        hasDueDate={hasDueDate}
      />
    </form>
  );
};

describe("hourly completion repeat", () => {
  it("reads the stored hourly interval and daily maximum without previewing fixed dates", async () => {
    const preview = vi.fn(() => HttpResponse.json({ occurrences: [] }));
    server.use(http.post("/api/v1/recurrence/preview", preview));
    renderWithProviders(<HourlyEditor />);

    expect(await screen.findByLabelText("Repeat every")).toHaveValue(4);
    expect(screen.getByLabelText("Maximum per day (optional)")).toHaveValue(3);
    expect(screen.getByRole("combobox", { name: "Frequency" })).toHaveTextContent("Hourly");
    expect(
      screen.getByText(/every 4 hours.*after completion.*at most 3 times per day/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/timezone of the person completing/)).toBeInTheDocument();
    expect(screen.queryByText("Next:")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/preferred first time/i)).not.toBeInTheDocument();
    expect(preview).not.toHaveBeenCalled();
  });

  it("switches a fixed task to hourly rolling in one callback", async () => {
    const change = vi.fn<(next: TaskRecurrenceValue) => void>();
    const user = userEvent.setup();
    renderWithProviders(
      <RecurrenceEditor
        kind="task"
        value={createRecurrenceFromPreset("weekly", "2026-10-05T08:00:00")}
        onChange={() => {}}
        strategy="fixed"
        onTaskChange={change}
        referenceDate="2026-10-05T08:00:00"
      />
    );
    await user.click(await screen.findByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Hourly (after completion)" }));

    expect(change).toHaveBeenCalledTimes(1);
    expect(change).toHaveBeenCalledWith({
      rule: createRecurrenceFromPreset("hourly"),
      strategy: "rolling",
      limit: null,
    });
  });

  it("keeps an invalid requested maximum visible and accepts a cap that exceeds the hours in a day", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HourlyEditor />);
    const maximum = await screen.findByLabelText("Maximum per day (optional)");
    await user.clear(maximum);
    await user.type(maximum, "25");

    expect(maximum).toHaveValue(25);
    expect(maximum).toBeInvalid();
    expect(screen.getByRole("alert")).toHaveTextContent(/not saved/i);
    await user.clear(maximum);
    await user.type(maximum, "7");
    expect(maximum).toHaveValue(7);
    expect(maximum).toBeValid();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("supports continuous hourly repeats with no daily maximum", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HourlyEditor />);
    const maximum = await screen.findByLabelText("Maximum per day (optional)");
    await user.clear(maximum);

    expect(maximum).toHaveValue(null);
    expect(maximum).toBeValid();
    expect(maximum).toHaveAttribute("placeholder", "Unlimited");
    expect(screen.getByText(/repeats every 4 hours.*after completion/i)).not.toHaveTextContent(
      "at most"
    );
  });

  it("requires the first task due date even for unlimited repeats and revalidates when supplied", async () => {
    const { rerender } = renderWithProviders(
      <HourlyEditor hasDueDate={false} initialLimit={null} />
    );
    const maximum = await screen.findByLabelText("Maximum per day (optional)");
    expect(maximum).toBeInvalid();
    expect(screen.getByRole("alert")).toHaveTextContent(/set a due date/i);

    rerender(<HourlyEditor hasDueDate initialLimit={null} />);
    expect(maximum).toBeValid();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("normalizes an hourly rule to daily and removes the cap when switching to fixed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HourlyEditor />);
    await user.click(await screen.findByRole("combobox", { name: "Repeat strategy" }));
    await user.click(await screen.findByRole("option", { name: "On schedule" }));

    expect(screen.queryByLabelText("Maximum per day (optional)")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Repeat strategy" })).toHaveTextContent(
      "On schedule"
    );
    expect(screen.getByRole("combobox", { name: "Frequency" })).toHaveTextContent("Daily");
    await user.click(screen.getByRole("combobox", { name: "Frequency" }));
    expect(screen.queryByRole("option", { name: "Hourly" })).not.toBeInTheDocument();
  });

  it("clears the cap when changing to a daily completion repeat", async () => {
    const user = userEvent.setup();
    renderWithProviders(<HourlyEditor />);
    await user.click(await screen.findByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Daily" }));

    expect(screen.queryByLabelText("Maximum per day (optional)")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Repeat strategy" })).toHaveTextContent(
      "After completion"
    );
    expect(screen.getByText(/repeats every day.*after completion/i)).not.toHaveTextContent(
      "at most"
    );
  });

  it("does not offer hourly presets or daily maximums for events", async () => {
    const user = userEvent.setup();
    renderEditor(null);
    await user.click(await screen.findByRole("combobox", { name: "Repeat" }));
    expect(
      screen.queryByRole("option", { name: "Hourly (after completion)" })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Every hour" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Maximum per day (optional)")).not.toBeInTheDocument();
  });
});

const ScheduleEditor = () => {
  const [rule, setRule] = useState<RecurrenceRule | null>(null);
  return <RecurrenceEditor kind="event" value={rule} onChange={setRule} hourly />;
};

describe("hourly schedule", () => {
  it("repeats every so many hours on a schedule, for a caller that offers it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ScheduleEditor />);
    await user.click(await screen.findByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Every hour" }));
    expect(screen.getByText("Repeats every hour")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Custom…" }));
    expect(screen.getByRole("combobox", { name: "Frequency" })).toHaveTextContent("Hourly");
    fireEvent.change(screen.getByLabelText("Repeat every"), { target: { value: "4" } });

    expect(screen.getByText("Repeats every 4 hours")).toBeInTheDocument();
    expect(screen.queryByLabelText("Maximum per day (optional)")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Repeat strategy" })).not.toBeInTheDocument();
  });
});
