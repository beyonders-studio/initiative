import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { type CounterRead, CounterViewMode } from "@/api/generated/initiativeAPI.schemas";
import { useSteppedCount } from "@/hooks/useCounters";

import { EditCounterDialog } from "./EditCounterDialog";

const counter = (overrides: Partial<CounterRead> = {}): CounterRead => ({
  id: 4,
  counter_group_id: 1,
  community_id: 1,
  name: "Hit points",
  color: null,
  count: "7",
  min: null,
  max: null,
  step: "1",
  initial_count: "0",
  view_mode: CounterViewMode.number,
  position: "0",
  properties: [],
  created_at: "2026-01-15T00:00:00.000Z",
  updated_at: "2026-01-15T00:00:00.000Z",
  ...overrides,
});

/** Serves `read`, and each change as the server would answer it. */
const serve = (read: CounterRead) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.get("/counters/:counterId", () => HttpResponse.json(read)),
    communityHttp.patch("/counters/:counterId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      return HttpResponse.json(Object.assign(read, body));
    })
  );
  return sent;
};

const Opened = ({ read, readOnly }: { read: CounterRead; readOnly: boolean }) => (
  <EditCounterDialog
    open
    onOpenChange={() => {}}
    groupId={1}
    initiativeId={1}
    counter={read}
    stepper={useSteppedCount(1)}
    readOnly={readOnly}
  />
);

const open = (read: CounterRead, readOnly = false) =>
  renderPage(() => <Opened read={read} readOnly={readOnly} />);

describe("a counter, opened to edit", () => {
  it("is drawn as its group lays it out, each field saved on its own", async () => {
    const read = counter();
    const sent = serve(read);
    open(read);
    const user = userEvent.setup();

    const step = within(await screen.findByRole("group", { name: "Step" })).getByRole("spinbutton");
    await user.clear(step);
    await user.type(step, "5{Enter}");

    await waitFor(() => expect(sent).toEqual([{ step: "5" }]));
    expect(screen.getByDisplayValue("Hit points")).toBeInTheDocument();
  });

  it("says why a bound it refuses was refused", async () => {
    const read = counter({ min: "0", max: "20", view_mode: CounterViewMode.progress_bar });
    serve(read);
    server.use(
      communityHttp.patch("/counters/:counterId", () =>
        HttpResponse.json({ detail: "COUNTER_VIEW_MODE_REQUIRES_BOUNDS" }, { status: 422 })
      )
    );
    open(read);
    const user = userEvent.setup();

    const min = within(await screen.findByRole("group", { name: "Min" })).getByRole("spinbutton");
    await user.clear(min);
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText("Progress bar and segmented clock require both min and max to be set")
    ).toBeInTheDocument();
  });

  it("shows a reader what it holds, with nothing to change it with", async () => {
    const read = counter({ min: "0", max: "20" });
    serve(read);
    open(read, true);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Hit points" })
    ).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
