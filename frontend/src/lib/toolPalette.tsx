/**
 * Per-tool command-palette sources — the ONE place a tool declares how its
 * entities surface in the command center: how much of its list the group
 * browses, what a row is labelled, its keywords, icon, and target route.
 *
 * `CommandCenter` renders one group per tool with `commandPalette: true` in
 * the registry by mounting a `<ToolPaletteGroup>` per tool; each group calls
 * its own source hook here (a component boundary per group keeps the rules of
 * hooks happy). The query behind every group is the tool's own entry in
 * `TOOL_HOOKS`, so a group reads the same list, under the same cache key, as
 * the tool's list page. A new tool adds one entry — the drift test asserts
 * every palette-enabled tool has one.
 *
 * These groups are what the palette shows while BROWSING. Once there is
 * something to search for, the community index answers instead, across every kind
 * of thing at once.
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import type { ToolPaletteListOptions } from "@/hooks/useToolPaletteList";
import { useToolPaletteList } from "@/hooks/useToolPaletteList";
import { USER_MENTION_PATTERN } from "@/lib/commentReferences";
import { fileIcon } from "@/lib/fileIcon";
import { TOOLS, toolCamelPlural, toolDetailRoute } from "@/lib/tools";

export interface PaletteItem {
  id: number;
  label: string;
  keywords: string[];
  /** Item icon; null falls back to the tool's registry icon. */
  icon: ReactNode | null;
  /** Community-relative target path. */
  path: string;
}

/** Only fetch while the palette is open for an authenticated user. */
export type PaletteSourceContext = ToolPaletteListOptions;

export interface ToolPaletteSource {
  /** Group heading; null hides the group entirely (e.g. no runtime config). */
  useHeading: () => string | null;
  useItems: (ctx: PaletteSourceContext) => PaletteItem[];
}

const useGroupHeading = (tool: Tool): string => {
  const { t } = useTranslation("command");
  return t(`groups.${toolCamelPlural(tool)}` as never);
};

/** How much of a list a group browses. Most tools take a round hundred; the
 *  two that carry text per row take a page. */
const BROWSE_PAGE = { page_size: 100 } as const;
const BROWSE_PAGE_HEAVY = { page_size: 25 } as const;

export const TOOL_PALETTE: Record<Tool, ToolPaletteSource> = {
  [Tool.project]: {
    useHeading: () => useGroupHeading(Tool.project),
    useItems: (ctx) => {
      // No page size: the sidebar already holds this exact query, so the group
      // reads what is cached rather than asking for a page of its own.
      const query = useToolPaletteList(TOOL_HOOKS[Tool.project].listQuery, undefined, ctx);
      return (query.data?.items ?? []).map((project) => ({
        id: project.id,
        label: project.name,
        keywords: [
          project.description ?? "",
          project.initiative?.name ?? "",
          ...(project.tags?.map((tag) => tag.name) ?? []),
        ],
        icon: project.icon ? <span className="text-base leading-none">{project.icon}</span> : null,
        path: toolDetailRoute(Tool.project, project.initiative_id, project.id),
      }));
    },
  },
  [Tool.file]: {
    useHeading: () => useGroupHeading(Tool.file),
    useItems: (ctx) => {
      // The 25 most recently updated. Narrowing by what was typed is the
      // index's job now, and it answers for every tool at once.
      const query = useToolPaletteList(TOOL_HOOKS[Tool.file].listQuery, BROWSE_PAGE_HEAVY, ctx);
      return (query.data?.items ?? []).map((doc) => {
        const { Icon: DocIcon, colorClass } = fileIcon({
          file_type: doc.file_type,
          smart_link_url: doc.smart_link_url,
        });
        return {
          id: doc.id,
          label: doc.name,
          keywords: [doc.initiative?.name ?? "", ...(doc.tags?.map((tag) => tag.name) ?? [])],
          icon: <DocIcon className={colorClass} />,
          path: toolDetailRoute(Tool.file, doc.initiative_id, doc.id),
        };
      });
    },
  },
  [Tool.queue]: {
    useHeading: () => useGroupHeading(Tool.queue),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.queue].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((queue) => ({
        id: queue.id,
        label: queue.name,
        keywords: [queue.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.queue, queue.initiative_id, queue.id),
      }));
    },
  },
  [Tool.counter_group]: {
    useHeading: () => useGroupHeading(Tool.counter_group),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.counter_group].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((group) => ({
        id: group.id,
        label: group.name,
        keywords: [group.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.counter_group, group.initiative_id, group.id),
      }));
    },
  },
  [Tool.calendar]: {
    useHeading: () => useGroupHeading(Tool.calendar),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.calendar].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((calendar) => ({
        id: calendar.id,
        label: calendar.name,
        keywords: [calendar.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.calendar, calendar.initiative_id, calendar.id),
      }));
    },
  },
  [Tool.dashboard]: {
    useHeading: () => useGroupHeading(Tool.dashboard),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.dashboard].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((dashboard) => ({
        id: dashboard.id,
        label: dashboard.name,
        keywords: [dashboard.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.dashboard, dashboard.initiative_id, dashboard.id),
      }));
    },
  },
  [Tool.post]: {
    useHeading: () => useGroupHeading(Tool.post),
    useItems: (ctx) => {
      // A page rather than the usual 100: posts carry their bodies, so a
      // hundred of them is a hundred editor states pulled in to fill a
      // dropdown. The palette matches on headline and excerpt, both of which
      // the first page already has.
      const query = useToolPaletteList(TOOL_HOOKS[Tool.post].listQuery, BROWSE_PAGE_HEAVY, ctx);
      return (query.data?.items ?? []).map((post) => ({
        id: post.id,
        label: post.name,
        // What it says, not the markup of who it mentions.
        keywords: [post.excerpt.replace(USER_MENTION_PATTERN, " ")],
        icon: null,
        path: toolDetailRoute(Tool.post, post.initiative_id, post.id),
      }));
    },
  },
  [Tool.library]: {
    useHeading: () => useGroupHeading(Tool.library),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.library].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((library) => ({
        id: library.id,
        label: library.name,
        keywords: [library.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.library, library.initiative_id, library.id),
      }));
    },
  },
  [Tool.wiki]: {
    useHeading: () => useGroupHeading(Tool.wiki),
    useItems: (ctx) => {
      const query = useToolPaletteList(TOOL_HOOKS[Tool.wiki].listQuery, BROWSE_PAGE, ctx);
      return (query.data?.items ?? []).map((wiki) => ({
        id: wiki.id,
        label: wiki.name,
        keywords: [wiki.description ?? ""],
        icon: null,
        path: toolDetailRoute(Tool.wiki, wiki.initiative_id, wiki.id),
      }));
    },
  },
};

/** Tools that get a command-palette group, in display order — every tool does. */
export const PALETTE_TOOLS: Tool[] = TOOLS;
