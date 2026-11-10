import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildInitiativeJoinRequest, buildUserSummary } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { InitiativeJoinRequestRead } from "@/api/generated/initiativeAPI.schemas";

import { JoinRequestQueue, type JoinRequestRow } from "./JoinRequestQueue";

const knock = (overrides: Partial<InitiativeJoinRequestRead> = {}) =>
  buildInitiativeJoinRequest({
    id: 11,
    user: buildUserSummary({ id: 42, display_name: "Ada Lovelace" }),
    message: "I run the Thursday session.",
    ...overrides,
  });

/** The queue as a page hands it over: its read, and what answering does. */
const renderQueue = (
  rows: JoinRequestRow[],
  { answeringId, onAnswer = vi.fn() }: Partial<Parameters<typeof JoinRequestQueue>[0]> = {}
) => {
  renderWithProviders(
    <>
      <div data-testid="mounted" />
      <JoinRequestQueue
        description="People who asked."
        queue={{ data: rows, isPending: false, isError: false, refetch: vi.fn() }}
        answeringId={answeringId}
        onAnswer={onAnswer}
      />
    </>
  );
  return onAnswer;
};

describe("JoinRequestQueue", () => {
  it("lists who knocked and what they said", () => {
    renderQueue([knock()]);

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("I run the Thursday session.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Deny/ })).toBeInTheDocument();
  });

  it("says so when a request carries no note", () => {
    renderQueue([knock({ message: null })]);

    expect(screen.getByText("No message")).toBeInTheDocument();
  });

  it("marks a requester turned down before", () => {
    renderQueue([knock({ prior_denials: 2 })]);

    // A denied requester may ask again, so the repeat is visible rather than
    // hidden.
    expect(screen.getByText("Denied 2 times before")).toBeInTheDocument();
  });

  it("leaves the marker off a first-time requester, and where the page knows of none", () => {
    // A community's queue carries no history of denials at all.
    renderQueue([knock(), { ...knock({ id: 12 }), prior_denials: undefined }]);

    expect(screen.queryByText(/Denied/)).not.toBeInTheDocument();
  });

  it.each([
    ["Approve", true],
    ["Deny", false],
  ])("hands %s back to the page with the row it answers", async (button, approved) => {
    const request = knock();
    const onAnswer = renderQueue([request]);

    await userEvent.click(screen.getByRole("button", { name: new RegExp(button) }));

    expect(onAnswer).toHaveBeenCalledWith(request, approved);
  });

  it("holds every answer while one is in flight", () => {
    renderQueue([knock(), knock({ id: 12 })], { answeringId: 11 });

    for (const button of screen.getAllByRole("button", { name: /Approve|Deny/ })) {
      expect(button).toBeDisabled();
    }
  });

  it("stays out of the way while there is nothing to answer", async () => {
    renderQueue([]);

    await screen.findByTestId("mounted");
    expect(screen.queryByText("Requests to join")).not.toBeInTheDocument();
  });

  it("counts the queue in its heading", () => {
    renderQueue([
      knock(),
      knock({ id: 12, user: buildUserSummary({ id: 43, display_name: "Grace" }) }),
    ]);

    const heading = screen.getByText("Requests to join");
    expect(within(heading).getByText("2")).toBeInTheDocument();
  });
});
