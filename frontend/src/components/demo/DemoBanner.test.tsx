/**
 * The top bar's first row: a demo visitor sees their copy and how long it has
 * left there, and every other account keeps the recents tabs.
 */
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildCommunity, buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { DemoBannerOrTabs } from "./DemoBanner";

const TopRow = () => (
  <DemoBannerOrTabs>
    <p>recent tabs</p>
  </DemoBannerOrTabs>
);

const mount = async (options: Parameters<typeof renderPage>[1]) => {
  const result = renderPage(TopRow, options);
  await waitFor(() => expect(result.router.state.status).toBe("idle"));
  return result;
};

describe("DemoBannerOrTabs", () => {
  it("shows a demo account its copy and the time left, in place of the tabs", async () => {
    // A little under 3 h 12 m, so the minutes round up to 12.
    const expiresAt = new Date(Date.now() + (192 * 60 - 20) * 1000).toISOString();
    await mount({
      auth: { user: buildUser({ demo_expires_at: expiresAt }) },
      communities: { communities: [buildCommunity({ name: "Rosie's Bakery" })] },
    });

    expect(
      await screen.findByText("This is a demo copy of Rosie's Bakery. It's deleted in 3h 12m.")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Visit the main site" })).toHaveAttribute(
      "href",
      "/welcome"
    );
    expect(screen.queryByText("recent tabs")).not.toBeInTheDocument();
  });

  it("keeps the tabs for an account without a copy", async () => {
    await mount({ auth: { user: buildUser({ demo_expires_at: null }) } });

    expect(await screen.findByText("recent tabs")).toBeInTheDocument();
    expect(screen.queryByText(/demo copy/)).not.toBeInTheDocument();
  });
});
