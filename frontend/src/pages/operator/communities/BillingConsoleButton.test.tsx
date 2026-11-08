/**
 * The billing portal opens from the website and the other apps. The iPhone
 * app shows what the button would have said, and nothing to press.
 */
import { Capacitor } from "@capacitor/core";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { BillingConsoleButton } from "./BillingConsoleButton";

const renderButton = () =>
  renderWithProviders(
    <BillingConsoleButton community={{ id: 1, name: "Acme" }} console="support">
      Gold
    </BillingConsoleButton>
  );

describe("BillingConsoleButton", () => {
  it.each(["web", "android", "electron"])("opens the portal on %s", (platform) => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);
    renderButton();

    expect(screen.getByRole("button", { name: "Gold" })).toBeInTheDocument();
  });

  it("shows the plan on an iPhone without a way to open the portal", () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");
    renderButton();

    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
