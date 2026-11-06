/**
 * The one place a tool list says the shelf exists.
 *
 * Two facts worth pinning: the link addresses the current community's marketplace
 * on the asking tool's own shelf, and a tool the catalog has nothing for
 * renders nothing at all — that is what lets a list mount the button without
 * first asking whether it applies.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";

import { BrowseMarketplaceButton } from "./BrowseMarketplaceButton";

describe("BrowseMarketplaceButton", () => {
  it("links to the tool's own marketplace shelf in the active community", async () => {
    renderPage(() => <BrowseMarketplaceButton tool={Tool.dashboard} />);

    const link = await screen.findByRole("link", { name: "Browse the marketplace" });
    expect(link).toHaveAttribute("href", "/c/1/marketplace?kind=dashboard");
  });

  it("renders nothing for a tool the marketplace has no shelf for", () => {
    const { container } = renderPage(() => <BrowseMarketplaceButton tool={Tool.counter_group} />);

    expect(container.querySelector("a")).toBeNull();
  });
});
