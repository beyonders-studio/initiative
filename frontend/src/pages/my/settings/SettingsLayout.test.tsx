/**
 * Which tabs a person is offered.
 *
 * Privacy is the one that isn't always there: with none of its sections to
 * set, it isn't offered rather than opening on a line saying there is nothing
 * here.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";

import { SettingsLayout } from "./SettingsLayout";

const mocks = vi.hoisted(() => ({ privacy: vi.fn() }));

vi.mock("@/hooks/usePrivacySections", () => ({ usePrivacySections: () => mocks.privacy() }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.privacy.mockReturnValue({ any: true });
});

const render = () => renderPage(SettingsLayout, { initialRoute: "/profile" });

describe("the settings tabs", () => {
  it("always offers the profile and the account", async () => {
    render();

    expect(await screen.findByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Account" })).toBeInTheDocument();
  });

  it("leaves out Privacy only when none of its sections has anything to set", async () => {
    mocks.privacy.mockReturnValue({ any: false });
    render();

    await screen.findByRole("tab", { name: "Profile" });
    expect(screen.queryByRole("tab", { name: /privacy/i })).not.toBeInTheDocument();
  });

  it("offers the Privacy tab, and its path resolves to a real route", async () => {
    const { createRouter } = await import("@tanstack/react-router");
    const { routeTree } = await import("@/routeTree.gen");

    renderPage(SettingsLayout);
    expect(await screen.findByRole("tab", { name: /privacy/i })).toBeInTheDocument();

    // Resolved through a real router over the generated tree: a tab pointing
    // at a path nothing registered would render exactly the same.
    const router = createRouter({ routeTree, context: buildRouterContext() });
    const matches = router.matchRoutes("/profile/privacy", {});
    expect(String(matches.at(-1)?.routeId)).toContain("profile/privacy");
  });
});
