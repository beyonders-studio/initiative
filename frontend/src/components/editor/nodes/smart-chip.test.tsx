/**
 * A chip is a word in somebody's sentence.
 *
 * It was set at a fixed `text-xs`, so dropped into a heading it stayed 12px
 * next to 30px text and read as a footnote stuck to the title. Sizing in `em`
 * makes it belong to whatever it sits in — and the padding has to follow, or
 * the box tightens around the text as the text grows.
 *
 * Asserted against the classes, because jsdom does no layout — which is why
 * nothing caught it.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { SmartChip } from "@/components/editor/nodes/smart-chip";

const chip = () => () => <SmartChip chipKind="task:status" entityId={12} fallback="Done" />;

describe("SmartChip", () => {
  it("takes its size from the text around it", async () => {
    renderPage(chip());

    const button = await screen.findByRole("button", { name: /done/i });

    // No fixed step anywhere on the box: size, padding and margin all scale.
    expect(button.className).not.toMatch(/\btext-(xs|sm|base|lg)\b/);
    expect(button.className).toContain("text-[0.85em]");
    expect(button.className).toContain("px-[0.4em]");
    expect(button.className).toContain("py-[0.15em]");
  });
});
