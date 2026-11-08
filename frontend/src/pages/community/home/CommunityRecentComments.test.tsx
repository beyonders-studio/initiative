/**
 * The feed clamps every comment to two lines, so a long one needs a way out.
 * jsdom lays nothing out — `scrollHeight`/`clientHeight` are always 0 — so the
 * clamp is simulated by making scrollHeight exceed clientHeight only while the
 * element still carries the clamp class.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { RecentActivityEntry } from "@/api/generated/initiativeAPI.schemas";

import { CommunityRecentComments } from "./CommunityRecentComments";

const buildEntry = (overrides: Partial<RecentActivityEntry> = {}): RecentActivityEntry =>
  ({
    comment_id: 1,
    content: "Looks good to me.",
    created_at: "2026-08-27T10:00:00Z",
    entity_type: "task",
    entity_id: 5,
    entity_name: "Fix login",
    project_id: 2,
    project_name: "Apollo",
    initiative_id: 1,
    author: { id: 9, display_name: "Ada Lovelace", email: "ada@example.com" },
    reactions: [],
    ...overrides,
  }) as RecentActivityEntry;

/** Makes clamped elements report overflow, the way a browser would. */
const simulateClamping = () => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() {
      return 40;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return String(this.className).includes("line-clamp") ? 400 : 40;
    },
  });
};

const showFeed = (entries: RecentActivityEntry[]) => {
  server.use(communityHttp.get("/comments/recent", () => HttpResponse.json(entries)));
  return renderPage(CommunityRecentComments);
};

afterEach(() => {
  // @ts-expect-error — restoring jsdom's own (absent) definitions
  delete HTMLElement.prototype.clientHeight;
  // @ts-expect-error — restoring jsdom's own (absent) definitions
  delete HTMLElement.prototype.scrollHeight;
});

describe("CommunityRecentComments read more", () => {
  it("offers read more on a comment that overflows its clamp", async () => {
    simulateClamping();
    showFeed([buildEntry({ content: "A very long comment. ".repeat(50) })]);

    expect(await screen.findByRole("button", { name: /read more/i })).toBeInTheDocument();
  });

  it("expands and collapses the comment", async () => {
    simulateClamping();
    const { container } = showFeed([buildEntry({ content: "A very long comment. ".repeat(50) })]);

    await userEvent.click(await screen.findByRole("button", { name: /read more/i }));

    expect(container.querySelector(".line-clamp-4")).toBeNull();
    const collapse = screen.getByRole("button", { name: /show less/i });

    await userEvent.click(collapse);

    expect(container.querySelector(".line-clamp-4")).not.toBeNull();
    expect(screen.getByRole("button", { name: /read more/i })).toBeInTheDocument();
  });

  it("leaves a comment that fits alone", async () => {
    showFeed([buildEntry({ content: "Short." })]);

    expect(await screen.findByText("Short.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /read more/i })).toBeNull();
  });

  it("names an image in the preview without loading it or adding a link", async () => {
    const { container } = showFeed([
      buildEntry({ content: "![a diagram](https://example.com/pic.png)" }),
    ]);

    expect(await screen.findByText("a diagram")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("renders a preview mention without nesting a link inside the entry link", async () => {
    showFeed([buildEntry({ content: "ping #task[Fix login](5)" })]);

    expect(await screen.findByText(/Task: Fix login/)).toBeInTheDocument();
    // One link for the entry itself; the mention must not add another.
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});

describe("CommunityRecentComments reactions", () => {
  it("shows the reactions a comment drew, read-only", async () => {
    showFeed([
      buildEntry({
        reactions: [{ emoji: "👍", count: 3, reacted: false, users: [] }],
      }),
    ]);

    const chip = await screen.findByRole("button", { name: /👍, 3 reactions/i });
    // The feed reports; reacting belongs in the thread the entry links to.
    expect(chip).toBeDisabled();
    expect(screen.queryByRole("button", { name: /add a reaction/i })).toBeNull();
  });

  it("adds nothing to an entry with no reactions", async () => {
    showFeed([buildEntry()]);

    expect(await screen.findByText("Looks good to me.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reaction/i })).toBeNull();
  });
});
