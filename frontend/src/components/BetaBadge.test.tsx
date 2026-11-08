import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { BetaBadge, isBetaVersion } from "./BetaBadge";

describe("BetaBadge", () => {
  it.each([
    ["0.77.0", true],
    ["v0.99.12", true],
    ["0.0.0-test", true],
    ["1.0.0", false],
    ["1.0.0-rc.1", false],
    ["2.3.4", false],
  ])("calls %s beta: %s", (version, beta) => {
    expect(isBetaVersion(version)).toBe(beta);
  });

  it("says Beta before 1.0.0", () => {
    renderWithProviders(<BetaBadge version="0.77.0" />);

    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("is gone from 1.0.0", () => {
    renderWithProviders(<BetaBadge version="1.0.0" />);

    expect(screen.queryByText("Beta")).not.toBeInTheDocument();
  });
});
