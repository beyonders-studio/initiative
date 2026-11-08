/**
 * Starting layouts: a home page arranged for one reason somebody is here.
 *
 * People land on Initiative for different things — their own list, a community
 * they follow, an organisation they run, work somebody assigned them — and each
 * wants something different first thing. A preset is a whole layout to start
 * from; picking one replaces the page, and everything about it can be changed
 * afterwards.
 *
 * Presets name no community: a widget that reads one (the activity feed) starts
 * on the reader's first and can be pointed elsewhere.
 */

import { clampGrid, HOME_LAYOUT_VERSION, type HomeLayout, type HomeWidgetOptions } from "./layout";
import type { HomeWidgetType } from "./widgetTypes";

/**
 * Each made for one reason to be here, and different enough from the others
 * that picking between them is a real choice:
 *
 * - `tasks` — My Tasks as it was, and the page nobody has arranged.
 * - `myDay` — somebody running their own life on it: today, the days ahead,
 *   their streak, then the whole list.
 * - `headsDown` — getting through it: a timer and what needs doing now, and
 *   nothing else to look at.
 * - `assigned` — somebody whose work is handed to them: the list first, the
 *   urgent part beside it, and what happened to their things.
 * - `community` — somebody here to follow a club or a space, not to work a list.
 * - `owner` — somebody keeping a community moving: its activity, what they
 *   bookmarked and what changed in its projects and dashboards, and their own
 *   list under that.
 */
export const HOME_PRESET_IDS = [
  "tasks",
  "myDay",
  "headsDown",
  "assigned",
  "community",
  "owner",
] as const;
export type HomePresetId = (typeof HOME_PRESET_IDS)[number];

/** What a page with nothing saved shows: My Tasks as it was, under a greeting. */
export const DEFAULT_HOME_PRESET: HomePresetId = "tasks";

type Placement = [HomeWidgetType, number, number, number, number, HomeWidgetOptions?];

const PLACEMENTS: Record<HomePresetId, Placement[]> = {
  tasks: [
    ["greeting", 0, 0, 12, 2],
    ["focus", 0, 2, 12, 5],
    ["tasks", 0, 7, 12, 12],
  ],
  myDay: [
    ["greeting", 0, 0, 12, 2],
    ["focus", 0, 2, 7, 8],
    ["comingUp", 7, 2, 5, 8],
    ["progress", 0, 10, 12, 3],
    ["tasks", 0, 13, 12, 10],
  ],
  headsDown: [
    ["clock", 0, 0, 4, 6, { mode: "timer" }],
    ["focus", 4, 0, 8, 6],
  ],
  assigned: [
    ["tasks", 0, 0, 8, 12],
    ["focus", 8, 0, 4, 6],
    ["activity", 8, 6, 4, 6, { view: "yours" }],
  ],
  community: [
    ["greeting", 0, 0, 12, 2],
    ["communities", 0, 2, 12, 6],
    ["activity", 0, 8, 8, 10],
    ["comingUp", 8, 8, 4, 10],
  ],
  owner: [
    ["greeting", 0, 0, 12, 2],
    ["activity", 0, 2, 7, 10],
    ["bookmarks", 7, 2, 5, 5],
    ["recent", 7, 7, 5, 5, { mode: "changed", tools: ["project", "dashboard"] }],
    ["tasks", 0, 12, 12, 10],
  ],
};

/** The preset as a layout of its own, ready to save. */
export const presetLayout = (id: HomePresetId): HomeLayout => {
  const counts = new Map<HomeWidgetType, number>();
  return {
    version: HOME_LAYOUT_VERSION,
    preset: id,
    widgets: PLACEMENTS[id].map(([type, x, y, w, h, options]) => {
      const n = (counts.get(type) ?? 0) + 1;
      counts.set(type, n);
      return {
        id: n === 1 ? type : `${type}-${n}`,
        type,
        grid: clampGrid(type, { x, y, w, h }),
        ...(options ? { options } : {}),
      };
    }),
  };
};
