/**
 * What an installed plug-in offers a member, read off its pinned definition.
 *
 * Three shapes, and the sidebar treats each differently:
 *
 * - **A surface** — one or more pages. Opens a page of its own.
 * - **Something to connect** — no page, but a credential the member or an
 *   admin supplies. Opens a dialog where they do that.
 * - **Neither** — it contributes widgets or data to somewhere else. There is
 *   nothing to open, so it does not take a row of its own.
 *
 * A surface says where it renders; *who* may open it there is the server's
 * answer (`surface_access`), computed by the same decision the handoff mint
 * makes: the placement's roles inside an initiative, the community's admins at
 * the community level and on an `admin_only` surface. Nothing here decides
 * access — this decides what is worth offering, so a reader is not handed a
 * door that would not open.
 */

import { initiativeRoute, TOOLS, toolListRoute } from "@/lib/tools";

export interface PluginPage {
  id: string;
  path: string;
  /** Where it renders. Absent means community-wide, the only placement there was. */
  scopes?: string[];
  /** Opened by the community's admins alone, whatever a placement allows. */
  admin_only?: boolean;
  /** Localized label, keyed by language. */
  name?: Record<string, string>;
  /** Browser features the surface asked its frame for, from the closed
   *  vocabulary the manifest validator checks. Absent means it asked for none. */
  capabilities?: string[];
}

/**
 * The `allow` attribute for a surface's frame.
 *
 * A frame is granted what its manifest named and nothing else, so a surface
 * that named nothing gets an empty attribute. Each entry defaults to the
 * frame's own origin, which is the plug-in's.
 */
export const pageAllow = (page: Pick<PluginPage, "capabilities"> | null | undefined): string =>
  (page?.capabilities ?? []).join("; ");

/** The places a surface can be reached from. */
export type SurfaceScope = "community" | "initiative";

/** Where the viewer may open one surface, as the server computed it. */
export interface SurfaceAccess {
  surface_id: string;
  openable_community_wide: boolean;
  openable_initiatives: number[];
}

/** Loose shape so this reads both the list and detail payloads. */
export interface PluginSurfaceSource {
  tool?: string | null;
  artifacts?: { type: string; id: number }[];
  definition?: Record<string, unknown> | null;
  /** The initiatives the seat placed this plug-in in, one entry each. */
  placements?: { initiative_id: number }[] | null;
  /** Where the viewer may open each surface. */
  surface_access?: SurfaceAccess[] | null;
}

/**
 * Whether a plug-in's initiative surfaces appear in one initiative.
 *
 * A plug-in appears only where it was placed. Placement is the community's own
 * answer to where a plug-in belongs, so it reads the same for everyone — an admin
 * who left an initiative out left it out for themselves too.
 */
export const placedIn = (
  plugin: Pick<PluginSurfaceSource, "placements">,
  initiativeId: number
): boolean => (plugin.placements ?? []).some((one) => one.initiative_id === initiativeId);

/** The pages a definition declares for one scope, whoever reads. */
export const declaredPages = (
  definition: Record<string, unknown> | null | undefined,
  scope: SurfaceScope
): PluginPage[] => {
  const pages = definition?.pages;
  if (!Array.isArray(pages)) return [];
  return pages.filter((page): page is PluginPage => {
    if (typeof page !== "object" || page === null) return false;
    const candidate = page as PluginPage;
    if (typeof candidate.id !== "string" || typeof candidate.path !== "string") return false;
    // Definitions pinned before surfaces could say where they belong carry no
    // scopes at all, and every one of them is community-wide.
    const scopes = Array.isArray(candidate.scopes) ? candidate.scopes : ["community"];
    return scopes.includes(scope);
  });
};

/**
 * The pages a plug-in offers this reader in one place.
 *
 * `initiativeId` is where: absent is the community level. A surface may declare
 * either scope or both, so this is a filter rather than a partition — a plug-in's
 * community-wide page and its per-initiative one are often the same surface reached
 * from two places. What the server did not say may be opened is not offered.
 */
export const pluginPages = (
  plugin: Pick<PluginSurfaceSource, "definition" | "surface_access"> | null | undefined,
  initiativeId?: number
): PluginPage[] => {
  const scope: SurfaceScope = initiativeId === undefined ? "community" : "initiative";
  const access = new Map((plugin?.surface_access ?? []).map((one) => [one.surface_id, one]));
  return declaredPages(plugin?.definition, scope).filter((page) => {
    const answer = access.get(page.id);
    if (!answer) return false;
    return initiativeId === undefined
      ? answer.openable_community_wide
      : answer.openable_initiatives.includes(initiativeId);
  });
};

/** Whether the plug-in declares any credential to fill in or connect. */
export const pluginHasConnections = (definition?: Record<string, unknown> | null): boolean =>
  Array.isArray(definition?.connections) && definition.connections.length > 0;

/**
 * Whether a plug-in has anything to place in an initiative: a page rendering
 * there, or fields, sections or actions on items, which the server draws in
 * the item's initiative to whoever the placement's roles admit, as it opens a
 * page. The same rule as a listing's `has_initiative_surfaces`, read off the
 * pinned definition.
 */
export const hasInitiativeSurfaces = (definition?: Record<string, unknown> | null): boolean =>
  declaredPages(definition, "initiative").length > 0 ||
  (Array.isArray(definition?.fields) && definition.fields.length > 0) ||
  (Array.isArray(definition?.parts) && definition.parts.length > 0) ||
  (Array.isArray(definition?.actions) && definition.actions.length > 0);

/**
 * Where a plug-in's community-wide entry leads.
 *
 * A tool-instance plug-in mounts an existing tool, so it links at the tool's own
 * route — the calendars a plug-in holds are just calendars. It links at the list
 * rather than at one of them, because a member may add more: the plug-in's home is
 * everything it holds, which is still the right address when it holds one. A
 * service plug-in with surfaces this reader can open gets a page. Anything else has
 * no route, and the caller decides what to do with the row.
 */
export const communityPluginPath = (
  plugin: PluginSurfaceSource & { id: number }
): string | null => {
  const tool = TOOLS.find((each) => each === plugin.tool);
  if (tool) {
    // No `/i/` prefix on purpose: a plug-in is installed per community, and the
    // calendars or contacts it holds belong to no initiative — the community
    // route is their real address, not a leftover.
    return toolListRoute(tool, null);
  }
  return pluginPages(plugin).length ? `/plugins/${plugin.id}` : null;
};

/**
 * Where a plug-in's entry inside one initiative leads.
 *
 * The same install — there is one of it per community, not one per initiative —
 * opened somewhere narrower. A tool-instance plug-in has none: the tool it mounted
 * already lives in an initiative of its own.
 */
export const initiativePluginPath = (
  plugin: PluginSurfaceSource & { id: number },
  initiativeId: number
): string | null => {
  if (plugin.tool || !placedIn(plugin, initiativeId)) return null;
  return pluginPages(plugin, initiativeId).length
    ? `${initiativeRoute(initiativeId)}/plugins/${plugin.id}`
    : null;
};
