import { render, waitFor } from "@testing-library/react";
import { type LucideIcon, Puzzle } from "lucide-react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { buildToolPlugin, buildToolRow, TOOL_PLUGIN_UID } from "@/__tests__/factories";
import contract from "@/contract/manifest.contract.json";

import {
  fieldSummary,
  installedTool,
  installedTools,
  isToolPluginKind,
  TOOL_PLUGIN_ICONS,
  toolOfKind,
  toolPluginRowRoute,
} from "./toolPlugins";

const uid = TOOL_PLUGIN_UID.toLowerCase();

describe("tool plug-in icons", () => {
  it("draws every icon the contract lets a tool name, and nothing else", () => {
    expect(Object.keys(TOOL_PLUGIN_ICONS).sort()).toEqual([...contract.enums.toolIcon].sort());
  });

  it("draws an icon that fails to load as a puzzle piece", async () => {
    const icons = TOOL_PLUGIN_ICONS as Record<string, () => Promise<never>>;
    icons.trophy = () => Promise.reject(new Error("offline"));
    const plugin = buildToolPlugin();
    (plugin.definition.tool as { icon: string }).icon = "trophy";
    const Icon = installedTool(plugin)?.icon as LucideIcon;

    const { container } = render(createElement(Icon));

    await waitFor(() => expect(container.querySelector(".lucide-puzzle")).not.toBeNull());
  });
});

describe("installedTool", () => {
  it("reads a tool and its item tables as kinds that carry the plug-in's uid", () => {
    const tool = installedTool(buildToolPlugin());
    expect(tool?.kind).toBe(`shelf.${uid}`);
    expect(isToolPluginKind(tool?.kind ?? "")).toBe(true);
    expect([...(tool?.tables.keys() ?? [])]).toEqual([`shelf.${uid}`, `book.${uid}`]);
    const shelf = tool?.tables.get(`shelf.${uid}`);
    expect(shelf?.items).toEqual([`book.${uid}`]);
    expect(shelf?.parent).toBeNull();
    expect(tool?.tables.get(`book.${uid}`)?.parent).toBe(`shelf.${uid}`);
  });

  it("draws an icon the app does not know as a puzzle piece", () => {
    const plugin = buildToolPlugin();
    (plugin.definition.tool as { icon: string }).icon = "not-an-icon";
    expect(installedTool(plugin)?.icon).toBe(Puzzle);
  });

  it("reads nothing from a plug-in of another kind", () => {
    expect(installedTool(buildToolPlugin({ definition: { plugin_kind: "service" } }))).toBeNull();
  });
});

describe("installedTools", () => {
  it("leaves out a plug-in that is off or out of reach", () => {
    const on = buildToolPlugin();
    const off = buildToolPlugin({ enabled: false, listing_uid: "OFF00000000000" });
    const away = buildToolPlugin({ available: false, listing_uid: "AWAY0000000000" });
    expect(installedTools([on, off, away]).map((tool) => tool.pluginId)).toEqual([on.id]);
  });

  it("finds the tool and table an item's kind belongs to", () => {
    const tools = installedTools([buildToolPlugin()]);
    expect(toolOfKind(tools, `book.${uid}`)?.table.name.en).toBe("Book");
    expect(toolOfKind(tools, "book")).toBeNull();
  });
});

describe("fieldSummary", () => {
  it("reads a counter's bounds from the fields its row holds", () => {
    const book = installedTool(buildToolPlugin())?.tables.get(`book.${uid}`);
    const pages = book?.fields.find((field) => field.key === "read");
    const row = buildToolRow({ fields: { read: 40, pages: 300 } });
    const summary = pages ? fieldSummary(pages, row, "en") : null;
    expect(summary?.value).toBe(40);
    expect(summary?.counter).toMatchObject({ min: 0, max: 300, step: 1, initial: 0 });
  });

  it("names a select's options in the reader's language", () => {
    const book = installedTool(buildToolPlugin())?.tables.get(`book.${uid}`);
    const shelf = book?.fields.find((field) => field.key === "status");
    const summary = shelf ? fieldSummary(shelf, buildToolRow(), "de") : null;
    expect(summary?.options?.map((option) => option.label)).toEqual(["Ungelesen", "Gelesen"]);
  });
});

describe("tool plug-in routes", () => {
  it("addresses any row by its kind under the initiative", () => {
    expect(toolPluginRowRoute(3, `book.${uid}`, 9)).toBe(`/i/3/t/book.${uid}/9`);
  });
});
