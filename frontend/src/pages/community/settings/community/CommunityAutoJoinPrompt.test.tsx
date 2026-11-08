/**
 * The prompt a listed community gets while nothing catches its new members.
 *
 * A community community is joinable by anyone, but a community membership on its own
 * puts nobody inside an initiative — so without auto-join the arrival sees an
 * empty community. What is checked here is that the admin is told exactly that, is
 * told what picking an initiative will do (and what it will not do to the people
 * already here), and that one pick sends the only field pair the server accepts.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCommunity, buildInitiative } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { CommunityAutoJoinPrompt } from "./CommunityAutoJoinPrompt";

const PROMPT_TITLE = "New members will arrive to an empty community";
const ACTION = "Set as the landing initiative";

/** The community's initiatives, plus a record of what each PATCH sent where. */
function stubInitiatives(initiatives: InitiativeRead[]) {
  const patches: { id: string; body: unknown }[] = [];
  server.use(
    communityHttp.get("/initiatives/", () => HttpResponse.json(initiatives)),
    communityHttp.patch("/initiatives/:id", async ({ params, request }) => {
      patches.push({ id: String(params.id), body: await request.json() });
      return HttpResponse.json(
        buildInitiative({ id: Number(params.id), name: "Welcome", join_policy: "open" })
      );
    })
  );
  return patches;
}

const renderPrompt = () =>
  renderWithProviders(<CommunityAutoJoinPrompt />, {
    communities: {
      activeCommunityId: 1,
      activeCommunity: buildCommunity({ id: 1, role: "admin", is_community: true }),
    },
  });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CommunityAutoJoinPrompt", () => {
  it("names the initiatives a newcomer could be landed in", async () => {
    stubInitiatives([
      buildInitiative({ id: 8, name: "Apollo" }),
      buildInitiative({ id: 9, name: "Borealis" }),
    ]);

    renderPrompt();

    expect(await screen.findByText(PROMPT_TITLE)).toBeVisible();
    expect(screen.getByRole("radio", { name: "Apollo" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Borealis" })).toBeInTheDocument();
  });

  it("spells out that the people already here are not swept in", async () => {
    stubInitiatives([buildInitiative({ id: 8, name: "Apollo" })]);

    renderPrompt();

    expect(await screen.findByText(/Members already here are not added/)).toBeVisible();
  });

  it("opens the picked initiative and flags it, in one request", async () => {
    const patches = stubInitiatives([
      buildInitiative({ id: 8, name: "Apollo" }),
      buildInitiative({ id: 9, name: "Borealis" }),
    ]);

    renderPrompt();

    await userEvent.click(await screen.findByRole("radio", { name: "Borealis" }));
    await userEvent.click(screen.getByRole("button", { name: ACTION }));

    await waitFor(() => expect(patches).toHaveLength(1));
    // Both halves together: the server refuses auto-join on anything but `open`.
    expect(patches[0]).toEqual({ id: "9", body: { join_policy: "open", auto_join: true } });
  });

  it("will not act until an initiative is picked", async () => {
    stubInitiatives([buildInitiative({ id: 8, name: "Apollo" })]);

    renderPrompt();

    expect(await screen.findByRole("button", { name: ACTION })).toBeDisabled();
  });

  it("says nothing once the community has somewhere to land people", async () => {
    stubInitiatives([
      buildInitiative({ id: 8, name: "Apollo" }),
      buildInitiative({ id: 9, name: "Welcome", join_policy: "open", auto_join: true }),
    ]);

    renderPrompt();

    // Give the list time to land before concluding the prompt is absent.
    await waitFor(() => expect(screen.queryByText(PROMPT_TITLE)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: ACTION })).not.toBeInTheDocument();
  });

  it("does not count an archived initiative as somewhere to land", async () => {
    // Enrolment skips archived initiatives, so one is not an answer.
    stubInitiatives([
      buildInitiative({ id: 8, name: "Apollo" }),
      buildInitiative({
        id: 9,
        name: "Retired",
        join_policy: "open",
        auto_join: true,
        archived_at: "2026-06-01T00:00:00.000Z",
      }),
    ]);

    renderPrompt();

    expect(await screen.findByText(PROMPT_TITLE)).toBeVisible();
    expect(screen.queryByRole("radio", { name: "Retired" })).not.toBeInTheDocument();
  });

  it("still explains itself to a community with no initiative to offer", async () => {
    stubInitiatives([]);

    renderPrompt();

    expect(await screen.findByText(PROMPT_TITLE)).toBeVisible();
    expect(screen.queryByRole("button", { name: ACTION })).not.toBeInTheDocument();
    expect(screen.getByText(/create an initiative/)).toBeVisible();
  });
});
