/**
 * Where a person lands when a connection's vendor flow ends: one word in the
 * address, one sentence on the page.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { ConnectedPage } from "./ConnectedPage";

describe("ConnectedPage", () => {
  it("asks the person to finish where they are signed in", async () => {
    renderPage(ConnectedPage, { routerSearch: { outcome: "sign_in_required" } });

    expect(
      await screen.findByText(
        "Finish connecting in the browser where you're signed in to Initiative, as the person who started it."
      )
    ).toBeInTheDocument();
  });

  it("says the organization is connected to another community", async () => {
    renderPage(ConnectedPage, { routerSearch: { outcome: "taken" } });

    expect(await screen.findByText("Already connected elsewhere")).toBeInTheDocument();
  });

  it("reads an ending it does not know as expired", async () => {
    renderPage(ConnectedPage, { routerSearch: { outcome: "whatever" } });

    expect(await screen.findByText("That link has expired")).toBeInTheDocument();
  });
});
