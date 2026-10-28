import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildPropertySummary, buildQueueItem } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { QueueItemRead } from "@/api/generated/initiativeAPI.schemas";

import { EditQueueItemDialog } from "./EditQueueItemDialog";

/** Serves `item`, and each change as the server would answer it. */
const serve = (item: QueueItemRead) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.get("/queue-items/:itemId", () => HttpResponse.json(item)),
    communityHttp.patch("/queue-items/:itemId", async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      return HttpResponse.json(Object.assign(item, body));
    })
  );
  return sent;
};

// Drawn on a page: its notes, like a description, hold the page while unsaved.
const open = (item: QueueItemRead, readOnly = false) =>
  renderPage(() => (
    <EditQueueItemDialog
      open
      onOpenChange={() => {}}
      queueId={1}
      initiativeId={1}
      item={item}
      readOnly={readOnly}
    />
  ));

describe("a queue item, opened", () => {
  it("is drawn as its queue lays it out, each field saved on its own", async () => {
    const item = buildQueueItem({ id: 7, label: "Goblin", position: 10 });
    const sent = serve(item);
    open(item);
    const user = userEvent.setup();

    const position = within(await screen.findByRole("group", { name: "Position" })).getByRole(
      "spinbutton"
    );
    await user.clear(position);
    await user.type(position, "15{Enter}");

    await waitFor(() => expect(sent).toEqual([{ position: 15 }]));
    expect(screen.getByDisplayValue("Goblin")).toBeInTheDocument();
  });

  it("shows a reader what it holds, with nothing to change it with", async () => {
    open(buildQueueItem({ id: 8, label: "Ogre", position: 3 }), true);

    expect(await screen.findByRole("heading", { name: "Ogre" })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    // An item with no properties shows a reader none, not an empty list.
    expect(screen.queryByText("Metadata")).not.toBeInTheDocument();
  });

  it("shows a reader the properties it holds", async () => {
    const property = buildPropertySummary({ name: "Initiative roll", value: "17" });
    open(buildQueueItem({ id: 9, label: "Troll", properties: [property] }), true);

    expect(await screen.findByText("Metadata")).toBeInTheDocument();
    expect(screen.getByText("Initiative roll")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
  });

  it("offers an editor a property to add where it has none", async () => {
    const item = buildQueueItem({ id: 10, label: "Imp" });
    serve(item);
    open(item);

    expect(await screen.findByRole("button", { name: "Add metadata" })).toBeInTheDocument();
  });
});
