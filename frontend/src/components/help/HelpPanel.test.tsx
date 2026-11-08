/**
 * Help: the user guide searched first, and the team asked where it did not
 * answer.
 */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { EMPTY_DRAFT, updateHelp } from "@/components/help/helpStore";
import { docsUrl } from "@/lib/links";

const CONTEXT = vi.hoisted(() => ({
  app_version: "0.79.0",
  platform: "web",
  locale: "en",
  theme: "dark",
  route: "/c/$communityId/projects/$projectId",
  viewport: "lg",
}));
const offer = vi.hoisted(() => ({
  mode: "form" as "form" | "email" | "none",
  contact: null as string | null,
  types: ["account", "community", "billing", "other"],
}));
const filed = vi.hoisted(() => ({ items: [] as { state: string }[] }));
const fileMutate = vi.hoisted(() => vi.fn());
const fileOptions = vi.hoisted(() => ({
  current: undefined as { onSuccess?: () => void } | undefined,
}));

vi.mock("@/api/generated/help/help", () => ({
  useReadHelpIndex: () => ({
    data: {
      items: [
        {
          title: "My invite link doesn't work",
          section: "FAQ › Getting in",
          location: "en/faq/#my-invite-link-doesnt-work",
          snippet: "Invite links expire, and an admin can turn them off.",
        },
        {
          title: "Projects and tasks",
          section: "Guides",
          location: "en/guides/projects/",
          snippet: "A project holds its tasks on a board, a list or a timeline.",
        },
        {
          title: "Due dates and reminders are a few hours off",
          section: "FAQ › Your account",
          location: "en/faq/#due-dates-and-reminders-are-a-few-hours-off",
          snippet: "Your time zone is set under My Settings.",
        },
      ],
    },
  }),
}));
vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 3 }));
vi.mock("@/components/tickets/DeviceContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/tickets/DeviceContext")>()),
  useDeviceContext: () => CONTEXT,
  useRouteTemplate: () => CONTEXT.route,
}));
vi.mock("@/hooks/useTickets", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useTickets")>()),
  useTicketAvailability: () => ({
    data: {
      support: {
        mode: offer.mode,
        contact: offer.contact,
        types: offer.types,
        evidence: { max_files: 2, max_bytes: 1024, types: ["image/png"] },
      },
    },
  }),
  useFiledTickets: () => ({ data: filed }),
  useFileTicket: (options: { onSuccess?: () => void }) => {
    fileOptions.current = options;
    return { mutate: fileMutate, isPending: false };
  },
}));

import { HelpHost } from "./HelpHost";

const openPanel = async () => {
  act(() => updateHelp({ open: true }));
  renderPage(HelpHost);
  return screen.findByRole("searchbox", { name: "Search the user guide" });
};

describe("Help", () => {
  beforeEach(() => {
    offer.mode = "form";
    offer.contact = null;
    filed.items = [];
  });
  afterEach(() => {
    updateHelp({
      open: false,
      view: "search",
      query: "",
      draft: EMPTY_DRAFT,
      communityId: undefined,
    });
  });

  it("leads with the user guide", async () => {
    await openPanel();
    expect(screen.getByRole("link", { name: /User guide/ })).toHaveAttribute("href", docsUrl());
  });

  it("opens on answers for the page, before anything is typed", async () => {
    await openPanel();
    expect(screen.getByText("For this page")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Projects and tasks/ })).toHaveAttribute(
      "href",
      docsUrl("en/guides/projects/")
    );
  });

  it("finds the answer to what is typed, and says when nothing matches", async () => {
    const search = await openPanel();
    const user = userEvent.setup();

    await user.type(search, "invite link");
    expect(
      await screen.findByRole("link", { name: /My invite link doesn't work/ })
    ).toHaveAttribute("href", docsUrl("en/faq/#my-invite-link-doesnt-work"));

    await user.clear(search);
    await user.type(search, "zebra");
    expect(
      await screen.findByText("Nothing in the user guide matches “zebra”.")
    ).toBeInTheDocument();
  });

  it("asks the team with the search as the start of the request", async () => {
    const search = await openPanel();
    const user = userEvent.setup();
    await user.type(search, "invite link expired");
    await user.click(screen.getByRole("button", { name: "Ask the team" }));
    expect(await screen.findByRole("textbox", { name: "What happened?" })).toHaveValue(
      "invite link expired"
    );
  });

  it("sends the request about the community, with this device's details", async () => {
    await openPanel();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask the team" }));
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();

    await user.type(
      screen.getByRole("textbox", { name: "What happened?" }),
      " Lost my phone {enter}I can't sign in."
    );
    await user.click(screen.getByRole("radio", { name: "This community" }));
    await user.click(send);

    expect(fileMutate).toHaveBeenCalledWith({
      ticket: {
        stream: "support",
        type: "community",
        community_id: 3,
        subject: "Lost my phone",
        body: "Lost my phone \nI can't sign in.",
        context: CONTEXT,
      },
      files: [],
    });
  });

  it("names no community about the account, and leaves the device out when asked", async () => {
    await openPanel();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask the team" }));
    await user.type(screen.getByRole("textbox", { name: "What happened?" }), "Change my email");
    await user.click(screen.getByRole("radio", { name: "My account" }));
    await user.click(screen.getByRole("switch", { name: "Send this device's details" }));
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(fileMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        ticket: expect.objectContaining({ type: "account", community_id: null, context: null }),
      })
    );
  });

  it("says it was sent, and where to follow it", async () => {
    await openPanel();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask the team" }));
    act(() => fileOptions.current?.onSuccess?.());
    expect(await screen.findByText("Sent to the team")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open My tickets" })).toHaveAttribute(
      "href",
      "/my-tickets"
    );
  });

  it("counts the reader's open requests", async () => {
    filed.items = [{ state: "waiting_on_you" }, { state: "closed" }];
    await openPanel();
    expect(screen.getByRole("link", { name: "1 open request" })).toBeInTheDocument();
  });

  it("gives the address where the server takes no requests", async () => {
    offer.mode = "email";
    offer.contact = "help@example.org";
    await openPanel();
    const foot = screen.getByText("help@example.org").closest("div") as HTMLElement;
    expect(within(foot).getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask the team" })).toBeNull();
  });
});
