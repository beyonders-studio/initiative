/**
 * "Who is this from?", answered before installing.
 *
 * One required name, shown the same way everywhere. Not a ranking by origin:
 * every listing on a deployment is there because whoever runs the server put it there,
 * so where it arrived from is not a distinction the reader needs — the one
 * exception being listings shipped in this build, which are credited to us
 * rather than to whatever their manifest claims.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildMarketplaceListing } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { MarketplaceListingSummary } from "@/api/generated/initiativeAPI.schemas";

import { ListingProvenance } from "./ListingProvenance";

const listing = (overrides: Partial<MarketplaceListingSummary> = {}) =>
  buildMarketplaceListing({ publisher: "Acme Widgets", ...overrides });

describe("ListingProvenance", () => {
  it("credits this build for a listing that ships with it", () => {
    renderWithProviders(
      <ListingProvenance listing={listing({ source: "builtin", publisher: "Initiative" })} />
    );
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("names the publisher of a registry listing", () => {
    renderWithProviders(<ListingProvenance listing={listing({ source: "registry" })} />);
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("names the publisher of an operator listing the same way", () => {
    // Same sentence for both, deliberately: the operator chose the registry
    // and dropped in the file, so neither is more theirs than the other.
    renderWithProviders(<ListingProvenance listing={listing({ source: "operator" })} />);
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("states the claim for a source it does not know", () => {
    renderWithProviders(
      <ListingProvenance listing={{ source: "something-new", publisher: "Acme Widgets" }} />
    );
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("renders no link of its own", () => {
    // The byline is text. A listing supplies no address the app will hand a
    // click to, so there is nothing here to vet.
    renderWithProviders(<ListingProvenance listing={listing({ source: "registry" })} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
