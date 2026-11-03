import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildShareStanding } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";

const failed = (status: number): AxiosError => {
  const error = new AxiosError("failed");
  error.response = {
    status,
    statusText: "",
    data: {},
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  };
  return error;
};

describe("ToolAccessStatus", () => {
  it.each([
    ["no access on a 403", failed(403), "Access Denied"],
    ["not found on a 404", failed(404), "Queue not found"],
    ["not found when there was nothing to read", null, "Queue not found"],
    ["the failure itself otherwise", failed(500), "Something went wrong. Please try again."],
  ])("says %s", async (_, error, title) => {
    renderPage(() => (
      <ToolAccessStatus error={error} keys="queues:" backTo="/" backLabel="Back to Queues" />
    ));

    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Queues" })).toBeInTheDocument();
  });
});

describe("ToolAccessStatus — something the reader may ask for", () => {
  const renderRefused = () =>
    renderPage(() => (
      <ToolAccessStatus
        error={failed(404)}
        keys="queues:"
        backTo="/"
        backLabel="Back to Queues"
        entity={{ kind: "task", id: 9 }}
      />
    ));

  it("asks for the tool above it at the level and with the note chosen", async () => {
    let body: unknown = null;
    server.use(
      communityHttp.get("/share-requests/standing", () =>
        HttpResponse.json(buildShareStanding({ resource_type: "project", resource_id: 4 }))
      ),
      communityHttp.post("/share-requests/", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ batch_id: "b", count: 1 }, { status: 201 });
      })
    );
    renderRefused();

    expect(await screen.findByText("You need access")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Edit" }));
    await userEvent.type(screen.getByLabelText("Note"), "For the launch");
    await userEvent.click(screen.getByRole("button", { name: "Request access" }));

    await waitFor(() =>
      expect(body).toEqual({
        resource_type: "project",
        resource_id: 4,
        level: "write",
        message: "For the launch",
      })
    );
    expect(screen.getByRole("link", { name: "Back to Queues" })).toBeInTheDocument();
  });

  it("says it was asked for instead of asking again", async () => {
    server.use(
      communityHttp.get("/share-requests/standing", () =>
        HttpResponse.json(buildShareStanding({ pending: "read" }))
      )
    );
    renderRefused();

    expect(await screen.findByText("Requested to view")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request access" })).not.toBeInTheDocument();
  });

  it("stays not found when there is nothing to ask for", async () => {
    renderRefused();

    expect(await screen.findByText("Queue not found")).toBeInTheDocument();
    expect(screen.queryByText("You need access")).not.toBeInTheDocument();
  });
});
