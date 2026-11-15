import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PopUp, PopUpDock, PopUpPanel, PopUpPill, PopUpTrigger } from "./pop-up";

const Timer = ({ defaultOpen }: { defaultOpen?: boolean }) => (
  <>
    <div data-testid="dock">
      <PopUpDock />
    </div>
    <PopUp defaultOpen={defaultOpen}>
      <PopUpPill aria-label="Timer">
        <span>24:13</span>
        <PopUpTrigger>Settings</PopUpTrigger>
      </PopUpPill>
      <PopUpPanel title="Timer settings">
        <p>Work for 25 minutes</p>
      </PopUpPanel>
    </PopUp>
  </>
);

describe("PopUp", () => {
  it("rests as its pill in the dock", () => {
    render(<Timer />);

    expect(screen.getByTestId("dock")).toHaveTextContent("24:13");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens its panel in place of the pill, and goes back to it", async () => {
    render(<Timer />);
    const settings = screen.getByRole("button", { name: "Settings" });

    await userEvent.click(settings);
    expect(screen.getByRole("dialog", { name: "Timer settings" })).toBeInTheDocument();
    expect(screen.queryByText("24:13")).not.toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("24:13")).toBeVisible();
    expect(settings).toHaveFocus();
  });

  it("leaves its panel open while the page is worked", async () => {
    render(
      <>
        <button type="button">On the page</button>
        <Timer defaultOpen />
      </>
    );

    await userEvent.click(screen.getByRole("button", { name: "On the page" }));
    expect(screen.getByRole("dialog", { name: "Timer settings" })).toBeInTheDocument();
  });

  it("draws nothing without a dock", () => {
    render(
      <PopUp defaultOpen>
        <PopUpPill>24:13</PopUpPill>
        <PopUpPanel title="Timer settings">Work</PopUpPanel>
      </PopUp>
    );

    expect(screen.queryByText("24:13")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
