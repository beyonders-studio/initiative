import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPropertySummary } from "@/__tests__/factories/properties";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { PropertyType } from "@/api/generated/initiativeAPI.schemas";
import { numberFormat } from "@/lib/intl";

import { PropertyValueCell } from "./PropertyValueCell";

describe("PropertyValueCell", () => {
  it("shows money in its property's currency", () => {
    renderWithProviders(
      <PropertyValueCell
        summary={buildPropertySummary({
          type: PropertyType.currency,
          currency: "EUR",
          value: 12.5,
        })}
      />
    );
    const expected = numberFormat(undefined, { style: "currency", currency: "EUR" }).format(12.5);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("draws a rating as its list says", () => {
    const rating = buildPropertySummary({ type: PropertyType.rating, value: 61 });
    const { rerender } = renderWithProviders(<PropertyValueCell summary={rating} />);
    expect(screen.getByText("61")).toBeInTheDocument();

    rerender(<PropertyValueCell summary={rating} display="stars" />);
    const stars = screen.getByRole("img", { name: "Rated 61 out of 100" });
    // 61 begins the fourth fifth, so four of the five stars are filled.
    expect(stars.querySelectorAll(".fill-current")).toHaveLength(4);

    rerender(<PropertyValueCell summary={rating} display="bar" />);
    const bar = screen.getByRole("img", { name: "Rated 61 out of 100" });
    expect(bar.firstElementChild).toHaveStyle({ width: "61%" });
  });
});
