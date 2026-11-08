import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const fileMutate = vi.fn();
const fileOptions = vi.hoisted(() => ({
  current: undefined as { onSuccess?: () => void } | undefined,
  pending: false,
}));
const feedbackMode = vi.hoisted(() => ({ current: "form" }));
const openExternal = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-router", async () => ({
  ...(await vi.importActual<typeof import("@tanstack/react-router")>("@tanstack/react-router")),
  useMatches: () => "/_serverRequired/_authenticated/c/$communityId/",
}));

vi.mock("@/hooks/useTickets", async () => ({
  ...(await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets")),
  useTicketAvailability: () => ({
    data: {
      feedback: {
        mode: feedbackMode.current,
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

const similar = vi.hoisted(() => ({ current: [] as unknown[] }));
const voteMutate = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useIdeas", async () => ({
  ...(await vi.importActual<typeof import("@/hooks/useIdeas")>("@/hooks/useIdeas")),
  useSimilarIdeas: (text: string) => ({ data: text ? similar.current : [] }),
  useVoteForIdea: () => ({ mutate: voteMutate, isPending: false }),
}));

vi.mock("@/lib/openExternal", () => ({ openExternal }));
vi.mock("@/lib/cloud", async () => ({
  ...(await vi.importActual<typeof import("@/lib/cloud")>("@/lib/cloud")),
  CLOUD_OPEN: true,
}));

import { CLOUD_ORIGIN } from "@/lib/cloud";

import { FeedbackHost, useFeedback } from "./FeedbackSheet";

/** The account menu's item, and the sheet the app shell draws. */
const Menu = () => {
  const feedback = useFeedback();
  return (
    <>
      {feedback.offered ? (
        <button type="button" onClick={feedback.open}>
          Open feedback
        </button>
      ) : null}
      <FeedbackHost />
    </>
  );
};

describe("FeedbackSheet", () => {
  beforeEach(() => {
    fileMutate.mockClear();
    openExternal.mockClear();
    fileOptions.pending = false;
    feedbackMode.current = "form";
    similar.current = [];
    voteMutate.mockReset();
  });

  const openAgain = async () => {
    const button = await screen.findByRole("button", { name: "Open feedback" });
    act(() => button.click());
  };

  // Each test signs in somebody new, whose draft starts empty.
  const open = async (user = buildUser()) => {
    const view = renderPage(Menu, { auth: { user } });
    await openAgain();
    return { ...view, user: userEvent.setup() };
  };

  it("opens Initiative Cloud's page from any other server, with where the app was", async () => {
    feedbackMode.current = "cloud";
    await open();
    const link = new URL(openExternal.mock.calls[0][0]);
    expect(link.origin + link.pathname).toBe(`${CLOUD_ORIGIN}/feedback`);
    const sent = new URLSearchParams(link.hash.slice(1));
    expect(sent.get("app_version")).toBe("0.0.0-test");
    expect(sent.get("route")).toBe("/c/$communityId");
    expect(screen.queryByLabelText("What would you like Initiative to do?")).toBeNull();
  });

  it("starts on an idea and sends what was written, the contact choice and where the app was", async () => {
    const { user } = await open();
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
        idea_task_id: null,
      },
      files: [],
    });
    act(() => fileOptions.current?.onSuccess?.());
    expect(screen.getByText("Thanks for the feedback!")).toHaveFocus();
  });

  it("offers the ideas like what is written, and joins what is sent to the one voted for", async () => {
    similar.current = [
      {
        task_id: 7,
        title: "Recurring events skip holidays",
        status: { id: 1, name: "Planned", color: null, category: "in_progress" },
        votes: 12,
        voted: false,
        closed: false,
        created_at: "2026-11-08T00:00:00Z",
      },
    ];
    const { user } = await open();
    const box = await screen.findByLabelText("What would you like Initiative to do?");
    await user.type(box, "Recurring events should skip holidays");
    await user.click(
      await screen.findByRole("button", { name: "Vote for Recurring events skip holidays" })
    );
    expect(voteMutate).toHaveBeenCalledWith({ taskId: 7, on: true }, expect.anything());
    act(() => voteMutate.mock.calls[0][1].onSuccess());
    expect(
      screen.getByText("Sending adds what you wrote to “Recurring events skip holidays”.")
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({ ticket: expect.objectContaining({ idea_task_id: 7 }) })
    );
    // Sent, the draft is done with.
    act(() => fileOptions.current?.onSuccess?.());
  });

  it("keeps the kind and the draft when closed, and leaves the app's details out when asked", async () => {
    const { user } = await open();
    await user.click(await screen.findByRole("radio", { name: "Something's not right" }));
    expect(
      screen.getByRole("button", { name: "Need somebody to sort it out for you? Ask for help" })
    ).toBeVisible();
    await user.type(screen.getByLabelText("What got in your way?"), "Export drops a row.");

    await user.keyboard("{Escape}");
    expect(screen.queryByLabelText("What got in your way?")).toBeNull();
    await openAgain();
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
    const first = await open(writer);
    await first.user.type(
      await screen.findByLabelText("What would you like Initiative to do?"),
      "Dark print."
    );
    first.unmount();

    fileOptions.pending = true;
    const again = await open(writer);
    expect(await screen.findByLabelText("What would you like Initiative to do?")).toHaveValue(
      "Dark print."
    );
    await again.user.keyboard("{Escape}");
    expect(screen.getByLabelText("What would you like Initiative to do?")).toBeInTheDocument();
    again.unmount();

    fileOptions.pending = false;
    await open(buildUser());
    expect(await screen.findByLabelText("What would you like Initiative to do?")).toHaveValue("");
  });
});
