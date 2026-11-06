import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("names the file a file field holds, or says the reader cannot open it", () => {
    const field = buildPropertySummary({
      type: MetadataType.file,
      value: { id: 7, name: "Mockup", file_type: "url", smart_link_url: null },
    });
    const { rerender } = renderWithProviders(<PropertyValueCell summary={field} />);
    expect(screen.getByText("Mockup")).toBeInTheDocument();

    rerender(<PropertyValueCell summary={{ ...field, value: { id: 7 } }} />);
    expect(screen.getByText("A file you can't open")).toBeInTheDocument();
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

  it("draws a counter as a number, a bar or a clock, from its initial value", () => {
    const counter = buildPropertySummary({
      type: MetadataType.counter,
      counter: { step: 1, min: 0, max: 4, initial: 3 },
      value: null,
    });
    const { rerender } = renderWithProviders(<PropertyValueCell summary={counter} />);
    expect(screen.getByText("3")).toBeInTheDocument();

    rerender(<PropertyValueCell summary={{ ...counter, value: 1 }} display="bar" />);
    expect(screen.getByRole("img", { name: "1 / 4" }).firstElementChild).toHaveStyle({
      width: "25%",
    });

    rerender(<PropertyValueCell summary={counter} display="clock" />);
    const clock = screen.getByRole("img", { name: "3 / 4" });
    // One segment a step, three of the four filled.
    expect(clock.querySelectorAll("path")).toHaveLength(4);
    expect(clock.querySelectorAll("path.fill-primary")).toHaveLength(3);
  });

  it("steps a counter it may change, showing the step at once and then the server's", async () => {
    const counter = buildPropertySummary({
      type: MetadataType.counter,
      name: "Seats",
      counter: { step: 1, min: 0, max: 4, initial: 3 },
      value: null,
    });
    let answer: (values: (typeof counter)[]) => void = () => undefined;
    const onStep = vi.fn(
      () =>
        new Promise<(typeof counter)[]>((resolve) => {
          answer = resolve;
        })
    );
    const onRow = vi.fn();
    renderWithProviders(
      <div onClick={onRow}>
        <PropertyValueCell summary={counter} onStep={onStep} />
      </div>
    );

    await userEvent.click(screen.getByRole("button", { name: "Step Seats up" }));
    expect(onStep).toHaveBeenCalledWith(true);
    expect(onRow).not.toHaveBeenCalled();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step Seats up" })).toBeDisabled();

    // Somebody else stepped it down meanwhile.
    answer([{ ...counter, value: 3 }]);
    expect(await screen.findByText("3")).toBeInTheDocument();
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
