import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

const mutate = vi.hoisted(() => vi.fn());
const listed = vi.hoisted(() => ({
  pages: [
    {
      total: 1,
      statuses: [
        { id: 1, name: "Under consideration", color: "#F59E0B", category: "todo" },
        { id: 2, name: "Shipped", color: "#10B981", category: "done" },
      ],
      items: [
        {
          task_id: 7,
          title: "Recurring events skip holidays",
          status: { id: 1, name: "Under consideration", color: "#F59E0B", category: "todo" },
          votes: 2,
          voted: false,
          closed: false,
          created_at: "2026-11-08T00:00:00Z",
        },
      ],
    },
  ],
}));

vi.mock("@/hooks/useIdeas", () => ({
  useIdeas: () => ({ data: listed, isSuccess: true, isError: false, hasNextPage: false }),
  useVoteForIdea: () => ({ mutate, isPending: false }),
}));

import { IdeasPage } from "./IdeasPage";

describe("IdeasPage", () => {
  it("lists the published ideas with their status and votes, and the board's statuses", async () => {
    renderPage(IdeasPage, { initialRoute: "/ideas", auth: { user: null } });
    expect(
      await screen.findByRole("link", { name: "Recurring events skip holidays" })
    ).toBeVisible();
    expect(screen.getByText("2 votes")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Shipped" })).toBeInTheDocument();
    // Only somebody signed in has votes of their own to narrow to.
    expect(screen.queryByRole("button", { name: "Voted by me" })).toBeNull();
  });

  it("sends somebody signed out to sign in to vote, and votes for somebody signed in", async () => {
    const user = userEvent.setup();
    const out = renderPage(IdeasPage, { initialRoute: "/ideas", auth: { user: null } });
    await user.click(
      await screen.findByRole("button", { name: "Vote for Recurring events skip holidays" })
    );
    expect(out.router.state.location.pathname).toBe("/login");
    expect(out.router.state.location.search).toEqual({ next: "/ideas" });
    expect(mutate).not.toHaveBeenCalled();
    out.unmount();

    renderPage(IdeasPage, { initialRoute: "/ideas", auth: { user: buildUser() } });
    await user.click(
      await screen.findByRole("button", { name: "Vote for Recurring events skip holidays" })
    );
    expect(mutate).toHaveBeenCalledWith({ taskId: 7, on: true });
  });
});
