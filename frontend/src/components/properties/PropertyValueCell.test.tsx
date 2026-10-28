import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPropertySummary } from "@/__tests__/factories/properties";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { MetadataType } from "@/api/generated/initiativeAPI.schemas";
import { numberFormat } from "@/lib/intl";

import { PropertyValueCell } from "./PropertyValueCell";

describe("PropertyValueCell", () => {
  it("shows money in its property's currency", () => {
    renderWithProviders(
      <PropertyValueCell
        summary={buildPropertySummary({
          type: MetadataType.currency,
          currency: "EUR",
          value: 12.5,
        })}
      />
    );
    const expected = numberFormat(undefined, { style: "currency", currency: "EUR" }).format(12.5);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("draws a scale as a number, stars or a bar, as its layout says", () => {
    const scale = buildPropertySummary({ type: MetadataType.scale, value: 61 });
    const { rerender } = renderWithProviders(<PropertyValueCell summary={scale} />);
    const percent = numberFormat("en", { style: "percent" }).format(0.61);
    expect(screen.getByText(percent)).toBeInTheDocument();

    rerender(<PropertyValueCell summary={scale} display="stars" />);
    const stars = screen.getByRole("img", { name: percent });
    // 61 begins the fourth fifth, so four of the five stars are filled.
    expect(stars.querySelectorAll(".fill-current")).toHaveLength(4);

    rerender(<PropertyValueCell summary={scale} display="bar" />);
    const bar = screen.getByRole("img", { name: percent });
    expect(bar.firstElementChild).toHaveStyle({ width: "61%" });
  });

  it("reads a scale kept with a state beside it by its figure", () => {
    renderWithProviders(
      <PropertyValueCell
        summary={buildPropertySummary({
          type: MetadataType.scale,
          value: { value: 40, state: { build: "running" } },
        })}
      />
    );
    expect(
      screen.getByText(numberFormat("en", { style: "percent" }).format(0.4))
    ).toBeInTheDocument();
  });
});
