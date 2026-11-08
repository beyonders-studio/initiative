/**
 * A long column overflows rather than squashing.
 *
 * A board column is a flex column that scrolls, and a card hides its own
 * overflow to clip a long title — which makes its automatic minimum size zero.
 * A column of 170 cards therefore shared its height out among them: every card
 * a hairline, its text spilling over the next, and nothing to scroll. What
 * stops that is one class on the card, so that is what this pins.
 *
 * jsdom does no layout, so the height cannot be measured here; the class that
 * decides it can, and a Playwright pass over a real dashboard is what would
 * measure it.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BoardNode as BoardScene } from "@/lib/widgets/sceneSpec";
import { dateTimeFormat } from "@/ui/lib/intl";

import { BoardNode } from "./BoardNode";

const board = (cards: number) => ({
  kind: "board" as const,
  columns: [
    {
      label: "Jordan Janzen",
      cards: Array.from({ length: cards }, (_, index) => ({ title: `Task ${index}` })),
    },
  ],
});

describe("a board column with more cards than fit", () => {
  it("keeps calendar dates fixed while timestamps use the viewer's zone", () => {
    const at = Date.parse("2026-08-03T00:00:00Z");
    const node: BoardScene = {
      kind: "board",
      columns: [
        {
          label: "Dates",
          cards: [
            { title: "Calendar day", date: at, date_only: true },
            { title: "Instant", date: at },
          ],
        },
      ],
    };
    render(<BoardNode node={node} />);
    const cards = screen.getAllByRole("article");
    expect(cards[0]).toHaveTextContent("Aug 3");
    expect(cards[1]).toHaveTextContent(
      dateTimeFormat(undefined, { month: "short", day: "numeric" }).format(at)
    );
  });

  it("keeps every card at its own height", () => {
    render(<BoardNode node={board(170)} />);
    const cards = screen.getAllByRole("article");

    expect(cards).toHaveLength(170);
    for (const card of cards) {
      expect(card.className).toContain("shrink-0");
    }
  });

  it("leaves the column itself scrollable", () => {
    const { container } = render(<BoardNode node={board(170)} />);
    const list = container.querySelector(".overflow-y-auto");

    expect(list).not.toBeNull();
    expect(list?.className).toContain("min-h-0");
  });
});
