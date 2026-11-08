import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { VersionDialog } from "./VersionDialog";

const changelog = vi.hoisted(() => ({
  entries: [] as { version: string; date: string; changes: string }[],
}));

vi.mock("@/hooks/useSettings", () => ({
  useChangelog: () => ({ data: changelog, isLoading: false }),
}));

const Footer = () => (
  <VersionDialog currentVersion="1.2.3" latestVersion="1.2.3">
    <button type="button">v1.2.3</button>
  </VersionDialog>
);

describe("VersionDialog", () => {
  afterEach(() => {
    changelog.entries = [];
  });

  it("leads, quietly, to the open-source licences", async () => {
    const user = userEvent.setup();
    const { router } = renderPage(Footer);

    await user.click(await screen.findByRole("button", { name: "v1.2.3" }));
    const link = await screen.findByRole("link", { name: "Open-source licences" });
    expect(link).toHaveAttribute("href", "/licences");

    await user.click(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/licences"));
    // The dialog closes on the way, so the page is not left behind it.
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Open-source licences" })).not.toBeInTheDocument()
    );
  });

  it("opens the newest release and keeps older ones closed until asked", async () => {
    changelog.entries = [
      { version: "1.2.3", date: "2026-10-20", changes: "- **Gantt view for projects.**" },
      { version: "1.2.2", date: "2026-10-01", changes: "- **Task types.**" },
    ];
    const user = userEvent.setup();
    renderPage(Footer);

    await user.click(await screen.findByRole("button", { name: "v1.2.3" }));
    const newest = await screen.findByRole("button", { name: /Version 1\.2\.3/ });
    const older = screen.getByRole("button", { name: /Version 1\.2\.2/ });
    expect(newest).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Gantt view for projects.")).toBeInTheDocument();
    expect(older).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Task types.")).not.toBeInTheDocument();

    await user.click(older);
    expect(older).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Task types.")).toBeInTheDocument();
  });
});
