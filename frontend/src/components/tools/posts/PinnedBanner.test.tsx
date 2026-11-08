/**
 * The pin's end date, where it is set.
 *
 * The backend has had an optional expiry since the tool shipped and nothing
 * could reach it — every pin was forever. What matters here is that the
 * affordance appears for somebody who may pin, stays away from everyone else,
 * and that pinning itself is untouched: the banner only exists once a post is
 * already pinned, so the one-click pin never grew a step.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildPost } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { PinnedBanner } from "./PinnedBanner";

const bannerPage = (props: Parameters<typeof PinnedBanner>[0]) => () => <PinnedBanner {...props} />;

const pinned = (overrides = {}) =>
  buildPost({ is_pinned: true, pinned_at: "2026-02-01T00:00:00.000Z", ...overrides });

describe("PinnedBanner", () => {
  it("renders nothing at all on a post that is not pinned", () => {
    const { container } = renderPage(bannerPage({ post: buildPost(), canPin: true }));
    expect(container.textContent).toBe("");
  });

  it("offers an end date to somebody who may pin", async () => {
    renderPage(bannerPage({ post: pinned(), canPin: true }));

    expect(await screen.findByText(/pinned to the top/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add an end date/i })).toBeInTheDocument();
  });

  it("offers a reader the sentence and no control", async () => {
    renderPage(bannerPage({ post: pinned(), canPin: false }));

    expect(await screen.findByText(/pinned to the top/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /end date/i })).not.toBeInTheDocument();
  });

  it("says when a pin already ends, and offers to change it", async () => {
    renderPage(
      bannerPage({ post: pinned({ pin_expires_at: "2026-03-01T09:00:00.000Z" }), canPin: true })
    );

    expect(await screen.findByText(/pinned until/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /change end date/i })).toBeInTheDocument();
  });

  // Removing is only offered where there is something to remove — otherwise it
  // is a button that does nothing, on the one dialog that exists to set a date.
  it("offers to remove an end date only when the pin has one", async () => {
    renderPage(bannerPage({ post: pinned(), canPin: true }));
    await userEvent.click(await screen.findByRole("button", { name: /add an end date/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove end date/i })).not.toBeInTheDocument();
  });

  it("offers to remove the end date a pin does have", async () => {
    renderPage(
      bannerPage({ post: pinned({ pin_expires_at: "2026-03-01T09:00:00.000Z" }), canPin: true })
    );
    await userEvent.click(await screen.findByRole("button", { name: /change end date/i }));

    expect(await screen.findByRole("button", { name: /remove end date/i })).toBeInTheDocument();
  });
});
