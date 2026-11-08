/**
 * A person's home views: several home pages, each a layout of its own, with
 * tabs to move between them — work on one, the soccer league on another.
 *
 * The list of views is one preference (`home:views`) and each view's layout
 * another (`home:view:<id>`), so every page gets the whole room a preference
 * has rather than sharing it.
 *
 * With nothing saved there is one view, `main`, showing the default layout.
 * Nothing is written until the reader changes something.
 */

const VIEWS_VERSION = 1;

/** The preference holding the list of views. */
export const HOME_VIEWS_KEY = "home:views";
/** The preference holding one view's layout. */
export const homeViewKey = (id: string) => `home:view:${id}`;

/** The view somebody has before they make another. */
export const MAIN_VIEW_ID = "main";
export const MAX_HOME_VIEWS = 10;
export const MAX_VIEW_NAME_LENGTH = 40;

const VIEW_ID = /^[a-z0-9]{1,16}$/;

export interface HomeViewEntry {
  id: string;
  name: string;
}

export interface HomeViews {
  version: typeof VIEWS_VERSION;
  views: HomeViewEntry[];
  /** The view opened last, which a bare `/` opens again. */
  current?: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/** A name as it is kept: trimmed, and no longer than a tab has room for. */
export const cleanViewName = (name: string) => name.trim().slice(0, MAX_VIEW_NAME_LENGTH);

/** The list a reader starts with: their one home page, under its default name. */
export const initialHomeViews = (name: string): HomeViews => ({
  version: VIEWS_VERSION,
  views: [{ id: MAIN_VIEW_ID, name }],
});

/** A stored list as this build can use it, or `null` when there is none worth keeping. */
export const readHomeViews = (raw: unknown): HomeViews | null => {
  if (!isRecord(raw) || !Array.isArray(raw.views)) return null;
  const seen = new Set<string>();
  const views: HomeViewEntry[] = [];
  for (const item of raw.views) {
    if (views.length >= MAX_HOME_VIEWS) break;
    if (!isRecord(item) || typeof item.id !== "string" || !VIEW_ID.test(item.id)) continue;
    if (seen.has(item.id)) continue;
    const name = typeof item.name === "string" ? cleanViewName(item.name) : "";
    if (!name) continue;
    seen.add(item.id);
    views.push({ id: item.id, name });
  }
  if (views.length === 0) return null;
  return {
    version: VIEWS_VERSION,
    views,
    ...(typeof raw.current === "string" && seen.has(raw.current) ? { current: raw.current } : {}),
  };
};

/** A fresh id no view in the list has. */
export const newViewId = (views: HomeViews): string => {
  const taken = new Set(views.views.map((view) => view.id));
  for (;;) {
    const id = Math.random().toString(36).slice(2, 10);
    if (id && VIEW_ID.test(id) && !taken.has(id)) return id;
  }
};

export const canAddView = (views: HomeViews) => views.views.length < MAX_HOME_VIEWS;

/** A new view, inserted after `after` (or last), and made the current one. */
export const addView = (views: HomeViews, entry: HomeViewEntry, after?: string): HomeViews => {
  if (!canAddView(views)) return views;
  const index = after ? views.views.findIndex((view) => view.id === after) : -1;
  const list = [...views.views];
  list.splice(index === -1 ? list.length : index + 1, 0, {
    id: entry.id,
    name: cleanViewName(entry.name),
  });
  return { ...views, views: list, current: entry.id };
};

export const renameView = (views: HomeViews, id: string, name: string): HomeViews => {
  const clean = cleanViewName(name);
  if (!clean) return views;
  return {
    ...views,
    views: views.views.map((view) => (view.id === id ? { ...view, name: clean } : view)),
  };
};

/** The list without the view, and which one to show in its place. The last
 *  view stays: a home page with no view would have nothing to draw. */
export const removeView = (views: HomeViews, id: string): { views: HomeViews; next: string } => {
  const index = views.views.findIndex((view) => view.id === id);
  if (index === -1 || views.views.length === 1) {
    return { views, next: views.current ?? views.views[0].id };
  }
  const list = views.views.filter((view) => view.id !== id);
  const next = (list[index] ?? list[index - 1]).id;
  return {
    views: { ...views, views: list, current: views.current === id ? next : views.current },
    next,
  };
};

/** One place left or right along the tabs. */
export const moveView = (views: HomeViews, id: string, step: -1 | 1): HomeViews => {
  const index = views.views.findIndex((view) => view.id === id);
  const target = index + step;
  if (index === -1 || target < 0 || target >= views.views.length) return views;
  const list = [...views.views];
  [list[index], list[target]] = [list[target], list[index]];
  return { ...views, views: list };
};
