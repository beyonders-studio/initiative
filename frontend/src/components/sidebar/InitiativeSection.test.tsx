/**
 * An initiative's tools in the sidebar: the built-in ones, then the tools the
 * community's tool plug-ins declare, each where the reader may open it.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  buildInitiative,
  buildToolPlugin,
  initiativeCan,
  TOOL_PLUGIN_UID,
} from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/sidebar/sidebar";
import { TOOLS } from "@/lib/tools";
import { TooltipProvider } from "@/ui/tooltip";

import { InitiativeSection } from "./InitiativeSection";

const kind = `shelf.${TOOL_PLUGIN_UID.toLowerCase()}`;

const counts = Object.fromEntries(TOOLS.map((tool) => [tool, 0])) as Record<Tool, number>;

const render = (view: string[], create: string[] = []) => {
  const initiative = buildInitiative({
    id: 3,
    can: initiativeCan({ view, create } as never),
  });
  return renderPage(() => (
    <TooltipProvider>
      <SidebarProvider>
        <InitiativeSection
          initiative={initiative}
          projects={[]}
          activeProjectId={null}
          counts={counts}
          plugins={[buildToolPlugin()]}
          activeCommunityId={1}
        />
      </SidebarProvider>
    </TooltipProvider>
  ));
};

describe("InitiativeSection", () => {
  it("lists an installed tool after the built-in ones, by its declared name and icon", async () => {
    render([Tool.wiki, kind, Tool.project]);

    const row = await screen.findByRole("link", { name: "Reading" });
    expect(row).toHaveAttribute("href", `/c/1/i/3/t/${kind}`);
    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links.indexOf("Reading")).toBeGreaterThan(
      links.findIndex((text) => text?.startsWith("Wikis"))
    );
    // Projects stay last, so their list opens beneath them.
    expect(links.findIndex((text) => text?.startsWith("Projects"))).toBeGreaterThan(
      links.indexOf("Reading")
    );
  });

  it("offers to add one where the reader may", async () => {
    render([kind], [kind]);

    // The tool's list, its add dialog open, as a built-in tool's create link.
    expect(await screen.findByRole("link", { name: "New Shelf" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/c/1/i/3/t/${kind}?create=`)
    );
  });

  it("leaves out a tool the reader may not open here", async () => {
    render([Tool.wiki]);

    expect(await screen.findByRole("link", { name: /Wikis/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Reading" })).toBeNull();
  });
});
