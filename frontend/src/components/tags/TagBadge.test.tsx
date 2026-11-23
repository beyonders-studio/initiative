/**
 * How much of a tag's name a badge shows.
 *
 * jsdom does no layout, so none of this can assert where the ellipsis lands —
 * that is the browser's job and the point of the change. What it can assert is
 * that the name reaches the DOM whole and the badge carries the CSS that lets
 * the browser cut it, which is exactly what a character cap took away.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildTagSummary } from "@/__tests__/factories";
import { TagBadge, TagBadgeList } from "@/components/tags/TagBadge";

const tag = (name: string) => ({ id: 1, name, color: "#3b82f6" });

const badgeFor = (name: string) => {
  const { container } = render(<TagBadge tag={tag(name)} />);
  return container.firstElementChild as HTMLElement;
};

describe("TagBadge", () => {
  // The old behaviour cut every segment to 12 characters and appended "…", so a
  // name with room to spare still came out truncated.
  it.each(["bug", "Documentation and research", "engineering-backlog/infrastructure"])(
    "renders %j in full rather than cutting it at a character count",
    (name) => {
      badgeFor(name);

      expect(screen.getByText(name)).toBeInTheDocument();
    }
  );

  it("leaves the cut to the browser, carrying the whole name on title", () => {
    const name = "A name long enough to need cutting somewhere";
    const badge = badgeFor(name);

    // `truncate` is overflow-hidden + ellipsis + nowrap; `max-w-full` is what
    // bounds the badge to its container. Together they are the truncation.
    expect(badge.className).toContain("max-w-full");
    expect(badge.querySelector(".truncate")).not.toBeNull();
    // The picker puts its badges inside a button, where each one is a flex
    // item. A flex item's default `min-width: auto` refuses to go below its
    // content, so without `min-w-0` a long tag pushed straight out of the box
    // instead of truncating inside it.
    expect(badge.className).toContain("min-w-0");
    expect(badge).toHaveAttribute("title", name);
  });

  it("keeps the remove control at full size while the label gives way", () => {
    const { container } = render(
      <TagBadge tag={tag("a-name-long-enough-to-squeeze")} onRemove={() => {}} />
    );

    const remove = container.querySelector("button");
    expect(remove?.className).toContain("shrink-0");
  });
});

describe("TagBadgeList", () => {
  it.each([
    { count: 0, limit: undefined, shown: 0, more: null },
    { count: 3, limit: undefined, shown: 3, more: null },
    { count: 5, limit: undefined, shown: 3, more: "+2" },
    { count: 5, limit: 4, shown: 4, more: "+1" },
  ])("shows $shown of $count tags at limit $limit", ({ count, limit, shown, more }) => {
    const tags = Array.from({ length: count }, () => buildTagSummary());

    render(<TagBadgeList tags={tags} limit={limit} />);

    expect(screen.queryAllByText(/^Tag \d+$/)).toHaveLength(shown);
    const overflow = screen.queryByText(/^\+\d+$/);
    expect(overflow?.textContent ?? null).toBe(more);
    // The collapsed tags are still named, on the count's title.
    expect(overflow?.title ?? null).toBe(
      more &&
        tags
          .slice(shown)
          .map((tag) => tag.name)
          .join(", ")
    );
  });
});
