import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { LicencesPage } from "./LicencesPage";

describe("LicencesPage", () => {
  it("shows the notices file the build put beside the app", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("Initiative includes the following third-party software and artwork.", {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPage(LicencesPage, { initialRoute: "/licences" });

    expect(
      await screen.findByText(/includes the following third-party software and artwork/)
    ).toBeInTheDocument();
    // From the origin root, not relative to the route: the phone apps serve
    // the bundle there too.
    expect(fetchMock).toHaveBeenCalledWith("/THIRD_PARTY_NOTICES.txt");
  });

  it("says so when the file cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    renderPage(LicencesPage, { initialRoute: "/licences" });

    expect(await screen.findByText("The licence notices could not be loaded.")).toBeInTheDocument();
  });
});
