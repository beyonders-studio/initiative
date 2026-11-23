/**
 * What the pages' tests can't reach: the icon set the contract allows, an icon
 * that can't be drawn, which installs count as tools, and a declared name in
 * another language. How a tool's kinds, tables, counters and routes read is
 * drawn by `ToolPluginRowPage.test.tsx` and the other pages' tests.
 */
import { render, waitFor } from "@testing-library/react";
import { type LucideIcon, Puzzle } from "lucide-react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRow, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import contract from "@/contract/manifest.contract.json";

import { fieldSummary, installedTool, installedTools, TOOL_PLUGIN_ICONS } from "./toolPlugins";

/** The shelf plug-in, naming `icon` for its tool. */
const withIcon = (icon: string) => {
  const plugin = buildToolPlugin();
  (plugin.definition.tool as { icon: string }).icon = icon;
  return plugin;
};

describe("tool plug-in icons", () => {
  it("draws every icon the contract lets a tool name, and nothing else", () => {
    expect(Object.keys(TOOL_PLUGIN_ICONS).sort()).toEqual([...contract.enums.toolIcon].sort());
  });

  it("draws an icon it does not know, or that fails to load, as a puzzle piece", async () => {
    expect(installedTool(withIcon("not-an-icon"))?.icon).toBe(Puzzle);

    const icons = TOOL_PLUGIN_ICONS as Record<string, () => Promise<never>>;
    const trophy = icons.trophy;
    icons.trophy = () => Promise.reject(new Error("offline"));
    try {
      const Icon = installedTool(withIcon("trophy"))?.icon as LucideIcon;
      const { container } = render(createElement(Icon));
      await waitFor(() => expect(container.querySelector(".lucide-puzzle")).not.toBeNull());
    } finally {
      icons.trophy = trophy;
    }
  });
});

describe("installedTools", () => {
  it("reads only a tool plug-in that is on and in reach", () => {
    const on = buildToolPlugin();
    const off = buildToolPlugin({ enabled: false, listing_uid: "OFF00000000000" });
    const away = buildToolPlugin({ available: false, listing_uid: "AWAY0000000000" });
    const service = buildToolPlugin({ definition: { plugin_kind: "service" } });
    expect(installedTools([on, off, away, service]).map((tool) => tool.pluginId)).toEqual([on.id]);
  });
});

describe("fieldSummary", () => {
  it("names a select's options in the reader's language", () => {
    const book = installedTool(buildToolPlugin())?.tables.get(
      `book.${TOOL_PLUGIN_UID.toLowerCase()}`
    );
    const status = book?.fields.find((field) => field.key === "status");
    const summary = status ? fieldSummary(status, buildToolRow(), "de") : null;
    expect(summary?.options?.map((option) => option.label)).toEqual(["Ungelesen", "Gelesen"]);
  });
});
