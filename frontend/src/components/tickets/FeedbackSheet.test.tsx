import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();
const fileOptions = vi.hoisted(() => ({
  current: undefined as { onSuccess?: () => void } | undefined,
}));

vi.mock("@tanstack/react-router", async () => ({
  ...(await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router")),
  useMatches: () => "/_serverRequired/_authenticated/c/$communityId/",
}));

vi.mock("@/hooks/useTickets", async () => ({
  ...(await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets")),
  useTicketAvailability: () => ({
    data: {
      feedback: {
        mode: "form",
        contact: null,
        evidence: { max_files: 3, max_bytes: 1024, types: ["image/png"] },
        types: [],
      },
      support: { mode: "form", contact: null, evidence: null, types: ["account", "other"] },
    },
  }),
  useFileTicket: (options: { onSuccess?: () => void }) => {
    fileOptions.current = options;
    return { mutate: fileMutate, isPending: false };
  },
}));

import { FeedbackHost, openFeedback, routeTemplate } from "./FeedbackSheet";

describe("routeTemplate", () => {
  it("drops the layout segments and keeps every id as its parameter", () => {
    expect(routeTemplate("/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/")).toBe(
      "/c/$communityId/i/$initiativeId"
    );
    expect(routeTemplate("/_serverRequired/_authenticated/")).toBe("/");
  });
});

describe("FeedbackSheet", () => {
  beforeEach(() => fileMutate.mockClear());

  // The draft outlives the sheet, so each test leaves it empty: sent or discarded.
  const open = () => {
    renderWithProviders(<FeedbackHost />, { auth: { user: buildUser() } });
    act(() => openFeedback());
    return userEvent.setup();
  };

  it("asks for a rating first, then sends it with the answers given and where the app was", async () => {
    const user = open();
    expect(await screen.findByText("Pick a star to rate it.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send feedback" })).toBeNull();

    await user.click(screen.getByRole("radio", { name: "4 stars: Really good" }));
    await user.type(screen.getByLabelText(/What do you wish it did\?/), "Dark print.");
    await user.click(screen.getByLabelText("You can contact me with questions about this"));
    // Only a low rating points at asking for help.
    expect(screen.queryByRole("button", { name: "Stuck on something? Ask for help" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(fileMutate).toHaveBeenCalledWith({
      ticket: {
        stream: "feedback",
        rating: 4,
        likes: null,
        wishes: "Dark print.",
        contactable: true,
        context: expect.objectContaining({ app_version: "0.0.0-test", route: "/c/$communityId" }),
      },
      files: [],
    });
    act(() => fileOptions.current?.onSuccess?.());
    expect(screen.getByText("Thanks for the feedback!")).toHaveFocus();
  });

  it("keeps the draft when closed, and leaves the app's details out when asked", async () => {
    const user = open();
    await user.click(await screen.findByRole("radio", { name: "2 stars: Needs work" }));
    expect(screen.getByRole("button", { name: "Stuck on something? Ask for help" })).toBeVisible();
    await user.type(screen.getByLabelText(/What do you like most\?/), "The board.");

    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText(/What do you like most\?/)).toBeNull();
    act(() => openFeedback());
    expect(await screen.findByLabelText(/What do you like most\?/)).toHaveValue("The board.");
    expect(screen.getByRole("radio", { name: "2 stars: Needs work" })).toBeChecked();

    await user.click(screen.getByRole("switch", { name: "Include your app version and page" }));
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        ticket: expect.objectContaining({ rating: 2, likes: "The board.", context: null }),
      })
    );
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByText("Pick a star to rate it.")).toBeInTheDocument();
  });
});
