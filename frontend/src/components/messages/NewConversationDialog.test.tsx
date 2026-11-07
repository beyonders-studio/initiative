/**
 * Reaching somebody the conversation list cannot offer.
 *
 * Two ways in, one field. What is worth proving is that they stay separate:
 * a partial term narrows the rosters and offers nothing to connect to, and a
 * whole handle offers the connection without needing the person to appear in
 * any roster at all.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { PersonRead } from "@/api/generated/initiativeAPI.schemas";

const mocks = vi.hoisted(() => ({
  sections: vi.fn(),
  more: vi.fn(),
  permissions: vi.fn(),
  requestConnection: vi.fn(),
  rosterCheck: vi.fn(),
  startGroup: vi.fn(),
}));

vi.mock("@/hooks/usePeople", () => ({
  usePeopleSections: (search: string) => mocks.sections(search),
  useMoreCommunityPeople: (communityId: number, search: string, enabled: boolean) =>
    mocks.more(communityId, search, enabled),
}));

// The field's own debounce is not what is on trial, and waiting 250ms of fake
// time in every case only makes them slower.
vi.mock("@/ui/lib/useDebouncedValue", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("@/hooks/useDirectMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useDmPermissions: (ids: number[]) => mocks.permissions(ids),
  useRequestConnection: () => ({ mutate: mocks.requestConnection, isPending: false }),
}));

vi.mock("@/hooks/useMyMessages", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useRosterCheck: (ids: number[]) => mocks.rosterCheck(ids),
  useStartGroup: () => ({ mutate: mocks.startGroup, isPending: false }),
}));

import { NewConversationDialog } from "./NewConversationDialog";

const person = (id: number, username: string): PersonRead => ({
  id,
  username,
  discriminator: 1234,
  display_name: null,
  avatar_url: null,
  status: "active",
  profile_decorations: { banner: null, frame: null, frame_tint: [], trophies: [], grad_year: null },
  community_role: null,
  presence: "offline",
  shared_community_ids: [7],
});

const section = (items: PersonRead[]) => ({
  community_id: 7,
  community_name: "Beyonders",
  icon_url: null,
  total_count: items.length,
  items,
  has_next: false,
});

const open = async () => {
  const result = renderPage(() => <NewConversationDialog />, { initialRoute: "/messages" });
  await userEvent.click(await screen.findByRole("button", { name: "Start a conversation" }));
  return result;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sections.mockReturnValue({
    data: { sections: [section([person(1, "ada")])], page: 1, page_size: 20 },
    isLoading: false,
  });
  mocks.more.mockReturnValue({
    data: undefined,
    isSuccess: false,
    isFetching: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
  });
  mocks.permissions.mockReturnValue({
    data: { permissions: { "1": { permission: "may_request", may_connect: true } } },
  });
  mocks.rosterCheck.mockReturnValue({ data: undefined, isFetching: false, isError: false });
});

describe("NewConversationDialog", () => {
  it("lists the people you share a community with, under that community", async () => {
    await open();

    expect(await screen.findByRole("heading", { name: /Beyonders/ })).toBeVisible();
    expect(screen.getByText("ada")).toBeVisible();
    expect(screen.getByText("Ask to message")).toBeVisible();
  });

  it("keeps acting on somebody possible when the way in is shut", async () => {
    // Refused: the row is no way in, and looking at them or ignoring them
    // still has to be possible.
    mocks.sections.mockReturnValue({
      data: { sections: [section([person(9, "hedy")])], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue({
      data: { permissions: { "9": { permission: "denied", may_connect: false } } },
    });
    await open();

    expect(screen.getByText("hedy").closest("button")).toBeDisabled();
    // The menu sits outside that button, and outside its disabling.
    expect(screen.getByRole("button", { name: /Actions for hedy/i })).toBeEnabled();
  });

  it("goes to the conversation rather than deciding anything about it", async () => {
    const { router } = await open();
    await userEvent.click(screen.getByText("ada"));

    await waitFor(() => expect(router.state.location.pathname).toBe("/messages"));
    expect(router.state.location.search).toEqual({ with: "ada1234" });
  });

  it("offers no way in for somebody the server refuses, and no reason why", async () => {
    mocks.more.mockReturnValue({
      data: undefined,
      isSuccess: false,
      isFetching: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
    });
    mocks.permissions.mockReturnValue({
      data: { permissions: { "1": { permission: "denied", may_connect: false } } },
    });
    await open();

    const row = screen.getByText("ada").closest("button") as HTMLButtonElement;
    expect(row).toBeDisabled();
    expect(screen.getByText("Not reachable")).toBeVisible();
  });

  it("waits for a whole handle before it offers a connection", async () => {
    await open();
    const field = screen.getByRole("textbox");

    await userEvent.type(field, "grace");
    expect(screen.queryByRole("button", { name: /Connect with/ })).not.toBeInTheDocument();

    await userEvent.type(field, "#0042");
    await userEvent.click(screen.getByRole("button", { name: "Connect with grace#0042" }));

    expect(mocks.requestConnection).toHaveBeenCalledWith(
      { data: { username: "grace", discriminator: 42 } },
      expect.anything()
    );
  });

  it("grows a long community rather than paging it, and only when asked", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    await open();

    // Nothing fetched for a roster nobody has reached the bottom of.
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", false);

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", true);
  });

  it("appends the pages it fetched under the ones it already had", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    mocks.more.mockReturnValue({
      data: { pages: [{ sections: [{ items: [person(2, "grace")] }] }] },
      isSuccess: true,
      isFetching: false,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
    });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    // The one already on screen stays where it was: a picker is read
    // downwards, and paging would take away the row just spotted.
    expect(await screen.findByText("ada")).toBeVisible();
    expect(screen.getByText("grace")).toBeVisible();
    // Nothing left to fetch, so nothing left to press.
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("puts an expanded community back to its first page under a new term", async () => {
    mocks.sections.mockReturnValue({
      data: {
        sections: [{ ...section([person(1, "ada")]), total_count: 42, has_next: true }],
        page: 1,
        page_size: 20,
      },
      isLoading: false,
    });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(mocks.more).toHaveBeenLastCalledWith(7, "", true);

    // A different term is a different set of people, and carrying the
    // expansion over would fetch a second page nobody asked for.
    await userEvent.type(screen.getByRole("textbox"), "gr");

    expect(mocks.more).toHaveBeenLastCalledWith(7, "gr", false);
  });

  it("asks the server for a term rather than filtering what it already had", async () => {
    await open();
    await userEvent.type(screen.getByRole("textbox"), "gra");

    expect(mocks.sections).toHaveBeenLastCalledWith("gra");
  });

  it("says nobody takes messages when the communities are there but the people are not", async () => {
    // A section arrives for a community that has other members in it, whether
    // or not any of them are listable, so an empty one is people declining
    // rather than an absence of people.
    mocks.sections.mockReturnValue({
      data: { sections: [section([])], page: 1, page_size: 20 },
      isLoading: false,
    });
    await open();

    expect(await screen.findByText(/has messaging turned on/)).toBeVisible();
  });

  it("says you share no communities when there are no sections at all", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [], page: 1, page_size: 20 },
      isLoading: false,
    });
    await open();

    expect(await screen.findByText(/You share no communities/)).toBeVisible();
  });
});

describe("gathering people into a group", () => {
  const two = [person(1, "ada"), person(2, "bo")];
  const reachable = {
    data: {
      permissions: {
        "1": { permission: "open", may_connect: true },
        "2": { permission: "open", may_connect: true },
      },
    },
  };

  it("adds without opening the person's own thread", async () => {
    // Picking is still one click for the ordinary case, so gathering is its
    // own control rather than the same gesture meaning two things.
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    await open();

    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));

    expect(await screen.findByRole("button", { name: "Remove ada#1234" })).toBeInTheDocument();
  });

  it("asks whether the roster could be a group as it is built", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    await open();

    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add bo#1234 to a group" }));

    await waitFor(() => expect(mocks.rosterCheck).toHaveBeenCalledWith([1, 2]));
  });

  it("names the pair who cannot reach each other, and refuses to propose", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    mocks.rosterCheck.mockReturnValue({
      data: { unreachable_pair: [1, 2], max_members: 40, too_large: false },
      isFetching: false,
      isError: false,
    });
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add bo#1234 to a group" }));

    expect(await screen.findByText(/cannot message each other yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start a group/ })).toBeDisabled();
    expect(mocks.startGroup).not.toHaveBeenCalled();
  });

  it("proposes the roster once it is reachable", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    mocks.rosterCheck.mockReturnValue({
      data: { unreachable_pair: [], max_members: 40, too_large: false },
      isFetching: false,
      isError: false,
    });
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add bo#1234 to a group" }));

    await userEvent.click(await screen.findByRole("button", { name: /Start a group/ }));

    expect(mocks.startGroup).toHaveBeenCalledWith([1, 2], expect.anything());
  });

  it("will not propose a roster that has not been checked yet", async () => {
    // Adding somebody starts a fresh check. Proposing before it answers hands
    // the refusal back from the server after the person has committed, which
    // is the late answer asking early was meant to replace.
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    mocks.rosterCheck.mockReturnValue({ data: undefined, isFetching: true, isError: false });
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add bo#1234 to a group" }));

    expect(screen.getByRole("button", { name: /Start a group/ })).toBeDisabled();
  });

  it("will not propose when the check could not be made", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue(reachable);
    mocks.rosterCheck.mockReturnValue({ data: undefined, isFetching: false, isError: true });
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Add ada#1234 to a group" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add bo#1234 to a group" }));

    expect(await screen.findByText(/could not be made/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start a group/ })).toBeDisabled();
  });

  it("will not gather somebody who cannot be reached", async () => {
    mocks.sections.mockReturnValue({
      data: { sections: [section(two)], page: 1, page_size: 20 },
      isLoading: false,
    });
    mocks.permissions.mockReturnValue({
      data: {
        permissions: {
          "1": { permission: "denied", may_connect: false },
          "2": { permission: "open", may_connect: true },
        },
      },
    });
    await open();

    expect(await screen.findByRole("button", { name: "Add ada#1234 to a group" })).toBeDisabled();
  });
});
