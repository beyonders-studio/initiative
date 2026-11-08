/**
 * What a card says before anyone clicks it.
 *
 * The card is the first place the provenance question gets answered, and the
 * one surface where the author's own address is deliberately withheld: the
 * whole card is already a link to the listing, and an anchor nested inside an
 * anchor is neither valid markup nor reliably clickable. That is what the
 * second test pins.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildMarketplaceListing } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { MarketplaceCard } from "./MarketplaceCard";

describe("MarketplaceCard", () => {
  // A card carries a router Link, so it mounts through renderPage and its
  // first paint is a tick away — hence findByText rather than getByText.
  it("names the author before anyone clicks through", async () => {
    const listing = buildMarketplaceListing({
      source: "operator",
      publisher: "Acme Widgets",
    });
    renderPage(() => <MarketplaceCard listing={listing} />);
    expect(await screen.findByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("puts no second link inside the card's own link", async () => {
    const listing = buildMarketplaceListing({
      source: "registry",
      publisher: "Acme Widgets",
    });
    renderPage(() => <MarketplaceCard listing={listing} />);
    expect(await screen.findByText("by Acme Widgets")).toBeInTheDocument();
    // Only the card itself.
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });
});
