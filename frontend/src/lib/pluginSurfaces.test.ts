/**
 * Which surfaces belong where, and which are worth offering to whom.
 *
 * Two readings that are easy to get wrong. A definition pinned before surfaces
 * could say where they belong carries no scopes, and every one of those is
 * community-wide — getting that wrong would empty the plug-in pages of every install
 * that predates it. And who may open a surface is the server's answer
 * (`surface_access`), so a surface the server did not say opens here is not
 * offered, whatever the definition declares.
 */

import { describe, expect, it } from "vitest";

import {
  communityPluginPath,
  declaredPages,
  initiativePluginPath,
  pageAllow,
  pluginPages,
  pluginPermissions,
  type SurfaceAccess,
} from "./pluginSurfaces";

const page = (id: string, scopes?: string[]) => ({
  id,
  path: `/page/${id}`,
  name: { en: id },
  ...(scopes ? { scopes } : {}),
});

const access = (
  surface_id: string,
  openable_community_wide: boolean,
  openable_initiatives: number[] = []
): SurfaceAccess => ({ surface_id, openable_community_wide, openable_initiatives });

describe("pageAllow", () => {
  it("grants a surface exactly what it asked for", () => {
    expect(pageAllow({ capabilities: ["clipboard-write", "fullscreen"] })).toBe(
      "clipboard-write; fullscreen"
    );
  });

  it("grants nothing to a surface that asked for nothing", () => {
    expect(pageAllow({ capabilities: [] })).toBe("");
  });

  it("grants nothing to a definition pinned before surfaces could ask", () => {
    expect(pageAllow({})).toBe("");
  });

  it("grants nothing when there is no surface open", () => {
    expect(pageAllow(null)).toBe("");
  });
});

describe("declaredPages", () => {
  it("reads a surface that says nothing as community-wide", () => {
    const definition = { pages: [page("board")] };
    expect(declaredPages(definition, "community").map((e) => e.id)).toEqual(["board"]);
    expect(declaredPages(definition, "initiative")).toEqual([]);
  });

  it("offers a surface in both places when it asked for both", () => {
    const definition = { pages: [page("runs", ["community", "initiative"])] };
    expect(declaredPages(definition, "community").map((e) => e.id)).toEqual(["runs"]);
    expect(declaredPages(definition, "initiative").map((e) => e.id)).toEqual(["runs"]);
  });

  it("ignores entries that are not surfaces", () => {
    const definition = { pages: [{ id: "no-path" }, null, "board", page("real")] };
    expect(declaredPages(definition, "community").map((e) => e.id)).toEqual(["real"]);
  });

  it("has nothing when the plug-in declares no pages", () => {
    expect(declaredPages({}, "community")).toEqual([]);
    expect(declaredPages(null, "community")).toEqual([]);
  });
});

describe("pluginPages", () => {
  it("offers a community-wide surface only where the server says it opens", () => {
    const definition = { pages: [page("board")] };
    expect(
      pluginPages({ definition, surface_access: [access("board", true)] }).map((e) => e.id)
    ).toEqual(["board"]);
    expect(pluginPages({ definition, surface_access: [access("board", false)] })).toEqual([]);
  });

  it("offers an initiative surface in the initiatives the server listed", () => {
    const definition = { pages: [page("runs", ["community", "initiative"])] };
    const plugin = { definition, surface_access: [access("runs", false, [4])] };
    expect(pluginPages(plugin, 4).map((e) => e.id)).toEqual(["runs"]);
    expect(pluginPages(plugin, 5)).toEqual([]);
    expect(pluginPages(plugin)).toEqual([]);
  });

  it("keeps an initiative-only surface off the community page", () => {
    // Even if an answer said otherwise, the surface never asked to render there.
    const definition = { pages: [page("runs", ["initiative"])] };
    const plugin = { definition, surface_access: [access("runs", true, [4])] };
    expect(pluginPages(plugin)).toEqual([]);
    expect(pluginPages(plugin, 4).map((e) => e.id)).toEqual(["runs"]);
  });

  it("offers nothing the server gave no answer for", () => {
    const definition = { pages: [page("board")] };
    expect(pluginPages({ definition })).toEqual([]);
    expect(pluginPages({ definition, surface_access: null })).toEqual([]);
    expect(pluginPages(null)).toEqual([]);
  });
});

describe("communityPluginPath", () => {
  it("gives a plug-in with a surface this reader opens a page", () => {
    expect(
      communityPluginPath({
        id: 7,
        definition: { pages: [page("board")] },
        surface_access: [access("board", true)],
      })
    ).toBe("/plugins/7");
  });

  it("gives a reader no page when no surface opens for them", () => {
    expect(
      communityPluginPath({
        id: 7,
        definition: { pages: [page("console", ["community"])] },
        surface_access: [access("console", false)],
      })
    ).toBeNull();
  });

  it("gives a plug-in with only initiative surfaces no community page", () => {
    expect(
      communityPluginPath({
        id: 7,
        definition: { pages: [page("runs", ["initiative"])] },
        surface_access: [access("runs", false, [4])],
      })
    ).toBeNull();
  });

  it("sends a tool-instance plug-in to the tool it mounted", () => {
    expect(
      communityPluginPath({ id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] })
    ).toBe("/calendars");
  });

  it("sends it to the list rather than to one of them", () => {
    // A member may add calendars to the plug-in, so its home is everything it
    // holds — the same address whether that is one calendar or six.
    const plugin = {
      id: 7,
      tool: "calendar",
      artifacts: [
        { type: "calendar", id: 3 },
        { type: "calendar", id: 4 },
      ],
    };
    expect(communityPluginPath(plugin)).toBe("/calendars");
  });
});

describe("initiativePluginPath", () => {
  const plugin = (openIn: number[]) => ({
    id: 7,
    definition: { pages: [page("runs", ["initiative"])] },
    surface_access: [access("runs", false, openIn)],
  });

  it("gives a row where the server says the reader opens a surface", () => {
    expect(initiativePluginPath(plugin([4]), 4)).toBe("/i/4/plugins/7");
    expect(initiativePluginPath(plugin([]), 4)).toBeNull();
  });

  it("gives no row to a plug-in with only a community-wide surface", () => {
    expect(
      initiativePluginPath(
        {
          id: 7,
          definition: { pages: [page("board")] },
          surface_access: [access("board", true)],
        },
        4
      )
    ).toBeNull();
  });

  it("gives a tool-instance plug-in no row of its own", () => {
    // The tool it mounted already lives in an initiative.
    expect(
      initiativePluginPath({ id: 7, tool: "calendar", artifacts: [{ type: "calendar", id: 3 }] }, 4)
    ).toBeNull();
  });
});

describe("pluginPermissions", () => {
  it("gives a plug-in that declares none use at each level, held by managers", () => {
    expect(pluginPermissions({})).toEqual([
      { id: "use", level: "initiative", name: null, members: false },
      { id: "use", level: "community", name: null, members: false },
    ]);
    expect(pluginPermissions(null)).toHaveLength(2);
  });

  it("lists each level's use first, named where the plug-in names it", () => {
    const permissions = [
      { id: "export", level: "initiative", name: { en: "Export" } },
      { id: "settings", level: "community", name: { en: "Settings" } },
      { id: "use", level: "initiative", name: { en: "See builds" }, members: true },
    ];
    expect(pluginPermissions({ permissions })).toEqual([
      { id: "use", level: "initiative", name: { en: "See builds" }, members: true },
      { id: "export", level: "initiative", name: { en: "Export" }, members: false },
      { id: "use", level: "community", name: null, members: false },
      { id: "settings", level: "community", name: { en: "Settings" }, members: false },
    ]);
  });
});
