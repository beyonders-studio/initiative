import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();
const fileOptions = vi.hoisted(() => ({
  current: undefined as { onSuccess?: () => void } | undefined,
  pending: false,
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
        types: ["idea", "problem", "praise"],
      },
      support: { mode: "form", contact: null, evidence: null, types: ["account", "other"] },
    },
  }),
  useFileTicket: (options: { onSuccess?: () => void }) => {
    fileOptions.current = options;
    return { mutate: fileMutate, isPending: fileOptions.pending };
  },
}));

import { FeedbackHost, openFeedback } from "./FeedbackSheet";

describe("FeedbackSheet", () => {
  beforeEach(() => {
    fileMutate.mockClear();
    fileOptions.pending = false;
  });

  // Each test signs in somebody new, whose draft starts empty.
  const open = (user = buildUser()) => {
    const view = renderWithProviders(<FeedbackHost />, { auth: { user } });
    act(() => openFeedback());
    return { ...view, user: userEvent.setup() };
  };

  it("starts on an idea and sends what was written, the contact choice and where the app was", async () => {
    const { user } = open();
    const box = await screen.findByLabelText("What would you like Initiative to do?");
    expect(box).toHaveFocus();
    expect(screen.getByRole("radio", { name: "Suggest an idea" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeDisabled();
    expect(screen.getByText("Write something to send.")).toBeInTheDocument();
    // Only something not right points at asking for help.
    expect(
      screen.queryByRole("button", { name: "Need somebody to sort it out for you? Ask for help" })
    ).toBeNull();

    await user.type(box, "Dark print.");
    await user.click(screen.getByLabelText("You can contact me with questions about this"));
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(fileMutate).toHaveBeenCalledWith({
      ticket: {
        stream: "feedback",
        type: "idea",
        body: "Dark print.",
        contactable: true,
        context: expect.objectContaining({ app_version: "0.0.0-test", route: "/c/$communityId" }),
      },
      files: [],
    });
    act(() => fileOptions.current?.onSuccess?.());
    expect(screen.getByText("Thanks for the feedback!")).toHaveFocus();
  });

  it("keeps the kind and the draft when closed, and leaves the app's details out when asked", async () => {
    const { user } = open();
    await user.click(await screen.findByRole("radio", { name: "Something's not right" }));
    expect(
      screen.getByRole("button", { name: "Need somebody to sort it out for you? Ask for help" })
    ).toBeVisible();
    await user.type(screen.getByLabelText("What got in your way?"), "Export drops a row.");

    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("What got in your way?")).toBeNull();
    act(() => openFeedback());
    expect(await screen.findByLabelText("What got in your way?")).toHaveValue(
      "Export drops a row."
    );
    expect(screen.getByRole("radio", { name: "Something's not right" })).toBeChecked();

    await user.click(screen.getByRole("switch", { name: "Include your app version and page" }));
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        ticket: expect.objectContaining({
          type: "problem",
          body: "Export drops a row.",
          context: null,
        }),
      })
    );
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByLabelText("What would you like Initiative to do?")).toHaveValue("");
  });

  it("opens a draft again only for the account that wrote it, and stays open while sending", async () => {
    const writer = buildUser();
    const first = open(writer);
    await first.user.type(
      await screen.findByLabelText("What would you like Initiative to do?"),
      "Dark print."
    );
    first.unmount();

    fileOptions.pending = true;
    const again = open(writer);
    expect(await screen.findByLabelText("What would you like Initiative to do?")).toHaveValue(
      "Dark print."
    );
    await again.user.keyboard("{Escape}");
    expect(screen.getByLabelText("What would you like Initiative to do?")).toBeInTheDocument();
    again.unmount();

    fileOptions.pending = false;
    open(buildUser());
    expect(await screen.findByLabelText("What would you like Initiative to do?")).toHaveValue("");
  });
});
