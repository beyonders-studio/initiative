import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildCommunity,
  buildInitiativeJoinRequest,
  buildUserSummary,
} from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import { queryClient } from "@/lib/queryClient";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "@/lib/mascotToast";

import { InitiativeJoinRequestQueue } from "./InitiativeJoinRequestQueue";

const INITIATIVE_ID = 7;

/** `appClient` mounts the queue against the app's own query client — the one
 *  the invalidation helpers address — so a refresh after an answer is
 *  observable rather than silently landing in another cache. */
const renderQueue = ({ appClient = false }: { appClient?: boolean } = {}) =>
  renderPage(
    () => (
      <>
        <div data-testid="mounted" />
        <InitiativeJoinRequestQueue initiativeId={INITIATIVE_ID} />
      </>
    ),
    {
      communities: {
        activeCommunityId: 1,
        activeCommunity: buildCommunity({ id: 1, role: "admin" }),
      },
      ...(appClient ? { queryClient } : {}),
    }
  );

/** The queue as the server would answer it, plus a record of what was asked. */
function stubQueue(requests: unknown[]) {
  const answered: string[] = [];
  server.use(
    communityHttp.get("/initiatives/:id/join-requests", () => HttpResponse.json(requests)),
    communityHttp.post("/initiatives/:id/join-requests/:requestId/approve", ({ params }) => {
      answered.push(`approve:${params.requestId}`);
      return HttpResponse.json(
        buildInitiativeJoinRequest({
          id: Number(params.requestId),
          status: "approved",
          user: buildUserSummary({ id: 42, display_name: "Ada Lovelace" }),
        })
      );
    }),
    communityHttp.post("/initiatives/:id/join-requests/:requestId/deny", ({ params }) => {
      answered.push(`deny:${params.requestId}`);
      return HttpResponse.json(
        buildInitiativeJoinRequest({
          id: Number(params.requestId),
          status: "denied",
          user: buildUserSummary({ id: 42, display_name: "Ada Lovelace" }),
        })
      );
    })
  );
  return answered;
}

const knock = (overrides = {}) =>
  buildInitiativeJoinRequest({
    id: 11,
    initiative_id: INITIATIVE_ID,
    user: buildUserSummary({ id: 42, display_name: "Ada Lovelace" }),
    message: "I run the Thursday session.",
    ...overrides,
  });

describe("InitiativeJoinRequestQueue", () => {
  // One test mounts against the app's own query client; clear it so nothing
  // carries between tests.
  beforeEach(() => {
    queryClient.clear();
  });

  it("lists who knocked and what they said", async () => {
    stubQueue([knock()]);

    renderQueue();

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("I run the Thursday session.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Deny/ })).toBeInTheDocument();
  });

  it("says so when a request carries no note", async () => {
    stubQueue([knock({ message: null })]);

    renderQueue();

    expect(await screen.findByText("No message")).toBeInTheDocument();
  });

  it("marks a requester this initiative has turned down before", async () => {
    stubQueue([knock({ prior_denials: 2 })]);

    renderQueue();

    // Design §13: a denied requester may ask again, so the repeat is visible
    // rather than hidden.
    expect(await screen.findByText("Denied 2 times before")).toBeInTheDocument();
  });

  it("leaves the marker off a first-time requester", async () => {
    stubQueue([knock()]);

    renderQueue();

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByText(/Denied/)).not.toBeInTheDocument();
  });

  it("approves a request and says who joined", async () => {
    const answered = stubQueue([knock()]);

    renderQueue();

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));

    await waitFor(() => expect(answered).toEqual(["approve:11"]));
    expect(toast.success).toHaveBeenCalledWith("Ada Lovelace joined the initiative.");
  });

  it("denies a request without letting anyone in", async () => {
    const answered = stubQueue([knock()]);

    renderQueue();

    await userEvent.click(await screen.findByRole("button", { name: /Deny/ }));

    await waitFor(() => expect(answered).toEqual(["deny:11"]));
    expect(toast.success).toHaveBeenCalledWith("Ada Lovelace's request was denied.");
  });

  it("drops the answered row when the queue re-reads", async () => {
    let resolved = false;
    server.use(
      communityHttp.get("/initiatives/:id/join-requests", () =>
        HttpResponse.json(resolved ? [] : [knock()])
      ),
      communityHttp.post("/initiatives/:id/join-requests/:requestId/approve", () => {
        resolved = true;
        return HttpResponse.json(buildInitiativeJoinRequest({ id: 11, status: "approved" }));
      })
    );

    renderQueue({ appClient: true });

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));

    await waitFor(() => expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument());
  });

  it("stays out of the way while there is nothing to answer", async () => {
    stubQueue([]);

    renderQueue();

    await screen.findByTestId("mounted");
    expect(screen.queryByText("Requests to join")).not.toBeInTheDocument();
  });

  it("counts the queue in its heading", async () => {
    stubQueue([
      knock(),
      knock({ id: 12, user: buildUserSummary({ id: 43, display_name: "Grace" }) }),
    ]);

    renderQueue();

    const heading = await screen.findByText("Requests to join");
    expect(within(heading).getByText("2")).toBeInTheDocument();
  });
});
