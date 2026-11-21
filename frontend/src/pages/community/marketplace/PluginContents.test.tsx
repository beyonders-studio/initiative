import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { PluginContents } from "./PluginContents";

const rowText = (label: string) =>
  screen.getByRole("rowheader", { name: label }).closest("tr")?.querySelector("td")?.textContent;

describe("PluginContents", () => {
  it("says where each name lands, beside the names that land there", async () => {
    renderWithProviders(
      <PluginContents
        definition={{
          plugin_kind: "service",
          pages: [
            { id: "home", path: "/", name: { en: "Overview", de: "Übersicht" } },
            { id: "board", path: "/b", name: { en: "Board" }, scopes: ["initiative"] },
          ],
          fields: [
            { key: "prs", name: { en: "Pull requests" }, on: ["task"] },
            { key: "due", name: { en: "Due" }, on: ["calendar_event"] },
          ],
          connections: [
            { id: "org", label: { en: "Organization" }, scope: "static" },
            { id: "me", label: { en: "Your account" }, scope: "interactive" },
          ],
        }}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "What it adds" }));
    expect(rowText("Pages")).toBe("Overview · for the whole communityBoard · inside initiatives");
    expect(rowText("Fields")).toBe("Pull requests · on tasksDue · on events");
    expect(rowText("Connections")).toBe(
      "Organization · an admin connects it onceYour account · each member connects their own"
    );
  });

  it("shows nothing for a definition with nothing to list", () => {
    renderWithProviders(<PluginContents definition={{ plugin_kind: "service" }} />);
    expect(screen.queryByRole("button", { name: "What it adds" })).not.toBeInTheDocument();
  });
});
