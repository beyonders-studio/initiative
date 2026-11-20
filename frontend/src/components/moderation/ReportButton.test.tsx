/**
 * The Report button.
 *
 * One rule holds on every surface it is drawn on, and it is the reason this is
 * a component rather than a line repeated five times: you cannot report your
 * own work, and a signed-out reader is offered nothing.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

vi.mock("@/hooks/useActiveCommunityId", () => ({ useActiveCommunityId: () => 3 }));
vi.mock("@/hooks/useTickets", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useTickets")>("@/hooks/useTickets");
  return {
    ...actual,
    useTicketAvailability: () => ({ data: undefined }),
    useFileTicket: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

import { ReportButton, ReportHost } from "./ReportButton";

const me = buildUser({ id: 10 });

describe("ReportButton", () => {
  // You cannot report your own work — deleting or editing it is already there,
  // and a report about yourself is somebody else's time — and a signed-out
  // reader is offered nothing.
  it.each([
    ["somebody else's work", me, 99, true],
    ["something with no author", me, null, true],
    ["your own work", me, me.id, false],
    ["anything, signed out", null, 99, false],
  ])("on %s it is offered: %s", (_label, user, authorId, offered) => {
    renderWithProviders(<ReportButton targetType="post" targetId={1} authorId={authorId} />, {
      auth: { user },
    });
    expect(Boolean(screen.queryByRole("button", { name: "Report" }))).toBe(offered);
  });

  it("opens a new report for each thing reported", async () => {
    renderWithProviders(
      <>
        <ReportButton targetType="post" targetId={1} />
        <ReportButton targetType="post" targetId={2} />
        <ReportHost />
      </>,
      { auth: { user: me } }
    );
    const user = userEvent.setup();
    const [first, second] = screen.getAllByRole("button", { name: "Report" });

    await user.click(first);
    expect(await screen.findByRole("dialog", { name: "Report this" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Anything else?"), "About the first post.");

    // The report holds the page still: it is closed before another is opened.
    await user.keyboard("{Escape}");
    await user.click(second);
    expect(await screen.findAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByLabelText("Anything else?")).toHaveValue("");
  });
});
