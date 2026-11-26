/**
 * Where a person lands when a connection's vendor flow ends: one word in the
 * address, one sentence on the page.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { ConnectedPage } from "./ConnectedPage";

describe("ConnectedPage", () => {
  it.each([
    [
      "sign_in_required",
      "Finish connecting in the browser where you're signed in to Initiative, as the person who started it.",
    ],
    [
      "app_only",
      "This connection was started in the Initiative app, so only the app can finish it. Connect again from the app.",
    ],
    // An ending it does not know reads as expired.
    ["whatever", "That link has expired"],
  ])("says what the %s ending means", async (outcome, text) => {
    renderPage(ConnectedPage, { routerSearch: { outcome } });
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});
