import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildReactionGroup } from "@/__tests__/factories/comment.factory";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { ReactionGroup, ReactionToggle } from "@/api/generated/initiativeAPI.schemas";
import { ReactionTarget } from "@/api/generated/initiativeAPI.schemas";

import { ReactionBar } from "./ReactionBar";
import { ReactionChip } from "./ReactionChip";

const THUMBS = "👍";
const PARTY = "🎉";

/** Registers the toggle handler; resolves the body it received and replies
 *  with whatever state the test says the server ends up in. */
const captureToggle = (reply: ReactionGroup[]) => {
  let received: ReactionToggle | null = null;
  server.use(
    communityHttp.put("/reactions/:targetType/:targetId", async ({ request }) => {
      received = (await request.json()) as ReactionToggle;
      return HttpResponse.json({
        target_type: "comment",
        target_id: 1,
        groups: reply,
      });
    })
  );
  return { body: () => received };
};

const renderBar = (groups: ReactionGroup[], props: { canReact?: boolean } = {}) =>
  renderWithProviders(
    <ReactionBar targetType={ReactionTarget.comment} targetId={1} groups={groups} {...props} />
  );

describe("ReactionBar", () => {
  it("renders a chip per emoji with its count", () => {
    renderBar([
      buildReactionGroup({ emoji: THUMBS, count: 3 }),
      buildReactionGroup({ emoji: PARTY, count: 1 }),
    ]);

    const thumbs = screen.getByRole("button", { name: /👍, 3 reactions/i });
    expect(thumbs).toHaveTextContent("3");
    // A chip's emoji is in colour; only the quick thumbs up waits in grey.
    expect(screen.getByText(THUMBS)).not.toHaveClass("grayscale");
    // One of something is what the emoji already says.
    expect(screen.getByRole("button", { name: /🎉, 1 reaction/i })).toHaveTextContent(/^🎉$/);
  });

  it("marks the viewer's own reaction as pressed", () => {
    renderBar([
      buildReactionGroup({ emoji: THUMBS, count: 1, reacted: true }),
      buildReactionGroup({ emoji: PARTY, count: 1, reacted: false }),
    ]);

    expect(screen.getByRole("button", { name: /👍/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /🎉/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("sends the chip's emoji to the toggle route", async () => {
    const toggled = captureToggle([buildReactionGroup({ emoji: THUMBS, count: 2, reacted: true })]);
    renderBar([buildReactionGroup({ emoji: THUMBS, count: 1 })]);

    await userEvent.click(screen.getByRole("button", { name: /👍/ }));

    await waitFor(() => expect(toggled.body()).not.toBeNull());
    expect(toggled.body()).toEqual({ emoji: THUMBS });
  });

  it("shows the state the server replies with", async () => {
    captureToggle([buildReactionGroup({ emoji: THUMBS, count: 2, reacted: true })]);
    renderBar([buildReactionGroup({ emoji: THUMBS, count: 1 })]);

    await userEvent.click(screen.getByRole("button", { name: /👍, 1 reaction/i }));

    expect(await screen.findByRole("button", { name: /👍, 2 reactions/i })).toBeInTheDocument();
  });

  it("gives way to fresh data instead of pinning our own last answer", async () => {
    // Our toggle's reply is shown immediately; the next list refetch (or a
    // realtime nudge because someone else reacted) has to win over it, or the
    // bar would show a stale count until the component unmounted.
    captureToggle([buildReactionGroup({ emoji: THUMBS, count: 2, reacted: true })]);
    const { rerender } = renderBar([buildReactionGroup({ emoji: THUMBS, count: 1 })]);

    await userEvent.click(screen.getByRole("button", { name: /👍, 1 reaction/i }));
    expect(await screen.findByRole("button", { name: /👍, 2 reactions/i })).toBeInTheDocument();

    rerender(
      <ReactionBar
        targetType={ReactionTarget.comment}
        targetId={1}
        groups={[buildReactionGroup({ emoji: THUMBS, count: 5, reacted: true })]}
      />
    );

    expect(screen.getByRole("button", { name: /👍, 5 reactions/i })).toBeInTheDocument();
  });

  it("offers the add button when the viewer may react", () => {
    renderBar([]);
    expect(screen.getByRole("button", { name: /add a reaction/i })).toBeInTheDocument();
  });

  it("gives a thumbs up in one tap", async () => {
    const toggled = captureToggle([buildReactionGroup({ emoji: THUMBS, count: 1, reacted: true })]);
    renderBar([buildReactionGroup({ emoji: PARTY, count: 1 })]);

    await userEvent.click(screen.getByRole("button", { name: /react with 👍/i }));

    await waitFor(() => expect(toggled.body()).toEqual({ emoji: THUMBS }));
    expect(await screen.findByRole("button", { name: /👍, 1 reaction/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("drops the thumbs-up shortcut once a thumbs-up chip is there to press", () => {
    renderBar([buildReactionGroup({ emoji: THUMBS, count: 1 })]);
    expect(screen.queryByRole("button", { name: /react with 👍/i })).not.toBeInTheDocument();
  });

  it("renders nothing at all in a read-only community with no reactions yet", () => {
    const { container } = renderBar([], { canReact: false });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows existing reactions read-only, with no way to add or toggle", () => {
    renderBar([buildReactionGroup({ emoji: THUMBS, count: 2 })], { canReact: false });

    expect(screen.getByRole("button", { name: /👍, 2 reactions/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /add a reaction/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /react with/i })).not.toBeInTheDocument();
  });
});

describe("ReactionChip", () => {
  it("keeps its emoji grey until pressed, where asked, and shows its count", () => {
    const { rerender } = renderWithProviders(
      <ReactionChip emoji={THUMBS} count={0} pressed={false} greyscale size="lg" />
    );
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(THUMBS)).toHaveClass("grayscale");
    expect(screen.getByText("0")).toBeInTheDocument();

    rerender(<ReactionChip emoji={THUMBS} count={1} pressed greyscale size="lg" />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(THUMBS)).not.toHaveClass("grayscale");
  });
});
