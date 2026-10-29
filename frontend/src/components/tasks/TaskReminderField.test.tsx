import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { buildTask } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { TaskReminderField } from "./TaskReminderField";

const state = (remind_at: string | null, reminded_at: string | null = null) => ({
  entity_type: "task",
  entity_id: 7,
  viewed_at: null,
  view_source: null,
  bookmarked_at: null,
  subscribed_at: null,
  subscribed: false,
  remind_at,
  reminded_at,
});

describe("TaskReminderField", () => {
  it("sets the reader's reminder from the picker and takes it off with Clear", async () => {
    const user = userEvent.setup();
    let remindAt: string | null = null;
    const written: string[] = [];
    server.use(
      http.get("/api/v1/c/3/personal-items/task/7", () => HttpResponse.json(state(remindAt))),
      http.put("/api/v1/c/3/personal-items/reminder/task/7", async ({ request }) => {
        const body = (await request.json()) as { remind_at: string };
        remindAt = body.remind_at;
        written.push(`set ${new Date(body.remind_at).getTime()}`);
        return HttpResponse.json(state(remindAt));
      }),
      http.delete("/api/v1/c/3/personal-items/reminder/task/7", () => {
        remindAt = null;
        written.push("clear");
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderWithProviders(<TaskReminderField task={buildTask({ id: 7 })} />, {
      communities: { activeCommunityId: 3 },
    });

    const trigger = await screen.findByRole("button", { name: /remind me/i });
    await waitFor(() => expect(trigger).toBeEnabled());
    expect(screen.getByText("Only you are reminded.")).toBeInTheDocument();
    await user.click(trigger);
    const typed = await screen.findByLabelText(/type or pick a date/i);
    await user.type(typed, "2026-11-02 09:30{Enter}");

    const at = new Date(2026, 10, 2, 9, 30).getTime();
    await waitFor(() => expect(written).toEqual([`set ${at}`]));

    await user.click(await screen.findByRole("button", { name: "No reminder" }));
    await waitFor(() => expect(written).toEqual([`set ${at}`, "clear"]));
  });

  it("says a repeating task's reminder moves with its due date", async () => {
    server.use(
      http.get("/api/v1/c/3/personal-items/task/7", () =>
        HttpResponse.json(state("2026-11-02T09:00:00Z"))
      )
    );
    renderWithProviders(
      <TaskReminderField
        task={buildTask({
          id: 7,
          due_date: "2026-11-03T09:00:00Z",
          recurrence: "RRULE:FREQ=WEEKLY",
        })}
      />,
      { communities: { activeCommunityId: 3 } }
    );
    expect(
      await screen.findByText("Each time it repeats, the reminder moves with its due date.")
    ).toBeInTheDocument();
  });

  it("says a reminder has gone out", async () => {
    server.use(
      http.get("/api/v1/c/3/personal-items/task/7", () =>
        HttpResponse.json(state("2026-01-02T09:00:00Z", "2026-01-02T09:00:30Z"))
      )
    );
    renderWithProviders(<TaskReminderField task={buildTask({ id: 7 })} />, {
      communities: { activeCommunityId: 3 },
    });
    expect(await screen.findByText("Reminder sent.")).toBeInTheDocument();
  });
});
