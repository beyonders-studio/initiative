/**
 * The desktop app's title bar. It draws only where the window leaves the page a
 * title bar to draw, so each test lends the navigator a window controls overlay.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { DesktopTitleBar } from "./DesktopTitleBar";

vi.mock("@/plugins/desktop", () => ({
  default: { setTitleBarColors: vi.fn().mockResolvedValue(undefined) },
}));

const lendOverlay = () => {
  const overlay = Object.assign(new EventTarget(), {
    visible: true,
    getTitlebarAreaRect: () => new DOMRect(0, 0, 800, 32),
  });
  Object.defineProperty(navigator, "windowControlsOverlay", {
    value: overlay,
    configurable: true,
  });
};

describe("DesktopTitleBar", () => {
  beforeEach(lendOverlay);
  afterEach(() => {
    Reflect.deleteProperty(navigator, "windowControlsOverlay");
  });

  it("copies the page's address on the server the app is signed in to", async () => {
    const user = userEvent.setup();
    renderPage(DesktopTitleBar, {
      initialRoute: "/c/$communityId/projects",
      routeParams: { communityId: "7" },
      routerSearch: { view: "board" },
      server: { getServerOrigin: () => "https://initiative.example.com" },
    });

    await user.click(await screen.findByRole("button", { name: "Copy link to this page" }));

    await waitFor(async () =>
      expect(await navigator.clipboard.readText()).toBe(
        "https://initiative.example.com/c/7/projects?view=board"
      )
    );
  });
});
