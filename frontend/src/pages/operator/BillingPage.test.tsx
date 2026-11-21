import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

let billingConfig: {
  url: string;
  operator_handoff: boolean;
  insights?: boolean;
  contracts?: boolean;
  directory?: boolean;
  control?: boolean;
} | null = {
  url: "https://billing.example.com",
  operator_handoff: true,
  insights: true,
  contracts: true,
  directory: true,
  control: true,
};

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({ billing: billingConfig }),
}));

const mintHandoff = vi.fn();
const mintContractsHandoff = vi.fn();
const mintDirectoryHandoff = vi.fn();
const mintControlHandoff = vi.fn();
vi.mock("@/api/generated/settings/settings", () => ({
  createBillingInsightsHandoff: () => mintHandoff(),
  createBillingContractsHandoff: () => mintContractsHandoff(),
  createBillingDirectoryHandoff: () => mintDirectoryHandoff(),
  createBillingControlHandoff: () => mintControlHandoff(),
}));

import { BillingPage } from "./BillingPage";

const renderPage = (role: "owner" | "operator" | "moderator" = "operator") =>
  renderWithProviders(<BillingPage />, {
    auth: { user: buildUser({ role }) },
  });

describe("BillingPage", () => {
  beforeEach(() => {
    mintHandoff.mockReset();
    mintContractsHandoff.mockReset();
    mintDirectoryHandoff.mockReset();
    mintControlHandoff.mockReset();
    billingConfig = {
      url: "https://billing.example.com",
      operator_handoff: true,
      insights: true,
      contracts: true,
      directory: true,
      control: true,
    };
  });

  it.each([
    ["directory", /open the directory/i, mintDirectoryHandoff, "owner"],
    ["control", /open control/i, mintControlHandoff, "owner"],
    ["contracts", /open contracts/i, mintContractsHandoff, "operator"],
    // Insights' handoff names no community.
    ["insights", /open billing insights/i, mintHandoff, "operator"],
  ] as const)("opens %s under its own door", async (door, name, mint, role) => {
    const location = { href: "" };
    const tab = { opener: {} as unknown, location, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mint.mockResolvedValue({ handoff_token: "tok-o", expires_in_seconds: 60 });

    renderPage(role);
    await userEvent.click(await screen.findByRole("button", { name }));

    const [path, fragment] = location.href.split("#");
    expect(path).toBe(`https://billing.example.com/${door}?lang=en`);
    expect(fragment).toBe(`${door}_handoff=tok-o`);
    expect(tab.opener).toBeNull();
    // Each door mints its own handoff, never insights'.
    if (door !== "insights") expect(mintHandoff).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("offers an operator neither the directory nor Control", async () => {
    renderPage();

    await screen.findByRole("button", { name: /open contracts/i });
    expect(screen.queryByRole("button", { name: /open the directory/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /open control/i })).toBeNull();
  });

  it("does not double the slash when the billing URL ends in one", async () => {
    billingConfig = { url: "https://example.com/billing/", operator_handoff: true, insights: true };
    const location = { href: "" };
    const tab = { opener: {} as unknown, location, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mintHandoff.mockResolvedValue({ handoff_token: "tok-9", expires_in_seconds: 60 });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /open billing insights/i }));

    expect(location.href.split("#")[0]).toBe("https://example.com/billing/insights?lang=en");
    openSpy.mockRestore();
  });

  it("closes the blank tab when minting fails", async () => {
    const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mintHandoff.mockRejectedValue(new Error("nope"));

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /open billing insights/i }));

    expect(tab.close).toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("offers no button when the deployment cannot open the page", async () => {
    billingConfig = {
      url: "https://billing.example.com",
      operator_handoff: true,
      insights: false,
      contracts: false,
    };
    renderPage();

    expect(await screen.findAllByText(/no billing service to open/i)).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /open billing insights/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /open contracts/i })).toBeNull();
  });

  it("is closed to a tier without billing.insights", async () => {
    renderPage("moderator");

    expect(await screen.findByText(/for platform operators and owners/i)).toBeInTheDocument();
    expect(mintHandoff).not.toHaveBeenCalled();
  });
});
