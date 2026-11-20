/**
 * Which tabs a person is offered.
 *
 * Privacy is the one that isn't always there: with none of its sections to
 * set, it isn't offered rather than opening on a line saying there is nothing
 * here.
 */
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { buildRouterContext, renderPage } from "@/__tests__/helpers/render";

import { SettingsLayout } from "./SettingsLayout";

describe("the settings tabs", () => {
  it("offers the profile, the account and Privacy, whose path resolves to a real route", async () => {
    const { createRouter } = await import("@tanstack/react-router");
    const { routeTree } = await import("@/routeTree.gen");

    renderPage(SettingsLayout, { initialRoute: "/profile" });
    expect(await screen.findByRole("tab", { name: /privacy/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Account" })).toBeInTheDocument();

    // Resolved through a real router over the generated tree: a tab pointing
    // at a path nothing registered would render exactly the same.
    const router = createRouter({ routeTree, context: buildRouterContext() });
    const matches = router.matchRoutes("/profile/privacy", {});
    expect(String(matches.at(-1)?.routeId)).toContain("profile/privacy");
  });

  it("leaves out Privacy only when none of its sections has anything to set", async () => {
    server.use(
      http.get("/api/v1/config", () =>
        HttpResponse.json({ direct_messages_enabled: false, engagement_ranking_enabled: false })
      )
    );
    renderPage(SettingsLayout, { initialRoute: "/profile" });

    await screen.findByRole("tab", { name: "Account" });
    // Waits for the config to land, which takes the tab away.
    await expect
      .poll(() => screen.queryByRole("tab", { name: /privacy/i }))
      .not.toBeInTheDocument();
  });
});
