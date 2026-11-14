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

const render = (props: Partial<React.ComponentProps<typeof ReportButton>> = {}) =>
  renderWithProviders(<ReportButton targetType="post" targetId={1} {...props} />, {
    auth: { user: me },
  });

describe("ReportButton", () => {
  it("is offered on somebody else's work", () => {
    render({ authorId: 99 });
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("is not offered on your own", () => {
    // Deleting or editing it is already there; a report about yourself is
    // somebody else's time.
    render({ authorId: me.id });
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
  });

  it("is offered on something with no author", () => {
    render({ authorId: null });
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
  });

  it("is offered to nobody when nobody is signed in", () => {
    renderWithProviders(<ReportButton targetType="post" targetId={1} />, {
      auth: { user: null },
    });
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
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
