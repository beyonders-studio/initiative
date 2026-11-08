/**
 * One notice on the board.
 *
 * Three things are load-bearing. A pinned post says so, and says *until when*
 * when the pin has an end — a notice about a date that stops shouting is the
 * whole point of the expiry. The pin control is offered on the reader's
 * authority over the initiative, not on their access to the post: an author
 * with owner-level access to their own notice still cannot lift it above
 * everyone else's, which is the rule the server enforces. And a scheduled
 * notice says it is not up yet, because the card is otherwise indistinguishable
 * from one that is.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildPost, ownerCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { PostCard } from "./PostCard";

// The headline is a router Link, so the card needs a router around it.
const cardPage = (props: Parameters<typeof PostCard>[0]) => () => <PostCard {...props} />;

/** One card, built from whatever this case varies. */
const renderCard = (
  overrides: Parameters<typeof buildPost>[0] = {},
  canPin?: boolean,
  canModerate?: boolean
) =>
  renderPage(
    cardPage({
      post: buildPost(overrides),
      ...(canPin === undefined ? {} : { canPin }),
      ...(canModerate === undefined ? {} : { canModerate }),
    })
  );

// The body is a Lexical editor; mounting one per card is the cost the board's
// small page size exists to bound, and none of it is what these cases are
// about.
vi.mock("@/pages/community/tools/posts/PostBody", () => ({
  PostBody: ({ body }: { body: Record<string, unknown> }) => (
    <div data-testid="post-body">{JSON.stringify(body)}</div>
  ),
}));

const PINNED_AT = "2026-02-01T00:00:00.000Z";

describe("PostCard", () => {
  it("shows the headline and the body", async () => {
    renderCard({ name: "Server maintenance Sunday" });

    expect(await screen.findByText("Server maintenance Sunday")).toBeInTheDocument();
    expect(screen.getByTestId("post-body")).toBeInTheDocument();
  });

  // A lapsed pin still carries pinned_at; the server decides `is_pinned`, and
  // the card must believe it rather than re-deriving from the columns.
  it.each([
    [
      "says a post is pinned, and until when if the pin ends",
      { is_pinned: true, pinned_at: PINNED_AT, pin_expires_at: "2026-03-01T00:00:00.000Z" },
      /pinned until/i,
    ],
    [
      "says only that it is pinned when the pin has no end",
      { is_pinned: true, pinned_at: PINNED_AT },
      /pinned to the top/i,
    ],
    [
      "treats a lapsed pin as not pinned",
      {
        is_pinned: false,
        pinned_at: "2026-01-01T00:00:00.000Z",
        pin_expires_at: "2026-01-02T00:00:00.000Z",
      },
      null,
    ],
  ])("%s", async (_label, overrides, shown) => {
    const { container } = renderCard(overrides);
    await screen.findByTestId("post-body");

    if (shown) {
      expect(screen.getByText(shown)).toBeInTheDocument();
    } else {
      expect(screen.queryByText(/pinned/i)).not.toBeInTheDocument();
      expect(container.querySelector(".border-primary\\/40")).toBeNull();
    }
  });

  it("offers the pin control only to a reader who may pin", async () => {
    const { unmount } = renderCard({ can: ownerCan() }, false);
    await screen.findByTestId("post-body");
    expect(screen.queryByRole("button", { name: /pin/i })).not.toBeInTheDocument();
    unmount();

    renderCard({ can: ownerCan() }, true);
    expect(await screen.findByRole("button", { name: /pin to top/i })).toBeInTheDocument();
  });

  it("offers unpinning on a post that is pinned", async () => {
    renderCard({ is_pinned: true, pinned_at: PINNED_AT }, true);

    expect(await screen.findByRole("button", { name: /unpin/i })).toBeInTheDocument();
  });

  // Both controls end the headline row together. Spacing them apart instead
  // put the pin wherever the report button left it — the middle of the card.
  it("keeps the pin and the report control together at the end of the row", async () => {
    const post = buildPost({ created_by: 999 });
    renderPage(cardPage({ post, canPin: true }));

    const pin = await screen.findByRole("button", { name: /pin to top/i });
    const flag = screen.getByRole("button", { name: /report/i });
    expect(pin.parentElement).toBe(flag.closest("button")?.parentElement);
    expect(pin.parentElement).not.toContainElement(screen.getByText(post.name));
  });

  // The board's moderators act on a notice where they read it; everybody else
  // is offered the report flag and nothing more.
  it("offers the moderation menu only to a moderator of the initiative", async () => {
    const { unmount } = renderCard({ created_by: 999 }, false, false);
    await screen.findByTestId("post-body");
    expect(screen.queryByRole("button", { name: /moderate/i })).not.toBeInTheDocument();
    unmount();

    const user = userEvent.setup();
    renderCard({ created_by: 999, comments_locked_at: "2026-03-01T00:00:00.000Z" }, false, true);
    await user.click(await screen.findByRole("button", { name: /moderate/i }));

    // A post takes reactions, so clearing them is offered. Its lock is on its
    // thread, not here.
    expect(await screen.findByRole("menuitem", { name: /clear reactions/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /warn/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /lock comments/i })).not.toBeInTheDocument();
  });

  // Reacting is a read-level gesture, so it is offered on the board itself
  // rather than only after opening the post.
  it("offers reactions on the board", async () => {
    renderCard();

    expect(await screen.findByRole("button", { name: /add a reaction/i })).toBeInTheDocument();
  });

  // "0 comments" reads as an absence; an invitation reads as a way in, so no
  // card ever counts none.
  it.each([
    ["says how many comments a post has", { comment_count: 3 }, "3 comments"],
    ["counts one comment as one", { comment_count: 1 }, "1 comment"],
    [
      "invites the first comment rather than counting none",
      { comment_count: 0 },
      /be the first to comment/i,
    ],
  ])("%s", async (_label, overrides, shown) => {
    renderCard(overrides);

    expect(await screen.findByText(shown)).toBeInTheDocument();
    expect(screen.queryByText(/0 comments/)).not.toBeInTheDocument();
  });

  it("says nothing about a thread that is turned off", async () => {
    renderCard({ comments_enabled: false, comment_count: 0 });
    await screen.findByTestId("post-body");

    expect(screen.queryByText(/be the first to comment/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/comment/i)).not.toBeInTheDocument();
  });

  // A card only reaches somebody who may see the notice, so a draft is on the
  // board of whoever wrote it and nobody else. It has to say so — otherwise it
  // reads as posted, and the author thinks a thing was announced that was not.
  it.each([
    [
      "says a scheduled notice is not up yet, and when it will be",
      { is_published: false, published_at: null, scheduled_for: "2026-03-01T09:00:00.000Z" },
      true,
    ],
    ["says nothing about scheduling on a notice that is up", {}, false],
  ])("%s", async (_label, overrides, scheduled) => {
    renderCard(overrides);
    await screen.findByTestId("post-body");

    if (scheduled) {
      expect(screen.getByText(/scheduled for/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /post now/i })).toBeInTheDocument();
    } else {
      expect(screen.queryByText(/scheduled for/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /post now/i })).not.toBeInTheDocument();
    }
  });

  // Being on screen is what marks a notice read, so the only control here is
  // the way back — and it belongs only on a notice that has one. A notice you
  // wrote is read by you and carries no receipt — the server refuses to record
  // one for an author — so there is nothing to put back.
  it.each([
    [
      "offers to mark a read notice of somebody else's unread",
      { is_read: true, created_by: 999 },
      true,
    ],
    ["offers nothing to mark on a notice still unread", { is_read: false }, false],
    ["offers no mark-unread on a notice the reader wrote", { is_read: true, created_by: 1 }, false],
  ])("%s", async (_label, overrides, offered) => {
    renderCard(overrides);
    await screen.findByTestId("post-body");

    const control = screen.queryByRole("button", { name: /mark unread/i });
    if (offered) {
      expect(control).toBeInTheDocument();
    } else {
      expect(control).not.toBeInTheDocument();
    }
  });

  // A board that shows only what was said makes every notice read as the app's
  // own announcement. A notice is somebody saying something.
  it("signs the notice with whoever wrote it", async () => {
    renderCard();

    expect(await screen.findByText(/author/)).toBeInTheDocument();
  });

  // Whether a notice landed is the point of putting it on a board, so the
  // count is on the card rather than behind the post's own page.
  it.each([
    ["says how many have read it", { read_count: 12 }, true],
    ["says nothing about a notice nobody has read", { read_count: 0 }, false],
  ])("%s", async (_label, overrides, counted) => {
    renderCard(overrides);
    await screen.findByTestId("post-body");

    const receipt = screen.queryByRole("button", { name: /read by/i });
    if (counted) {
      expect(receipt).toHaveAccessibleName(/read by 12/i);
    } else {
      expect(receipt).not.toBeInTheDocument();
    }
  });
});
