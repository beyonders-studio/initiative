/**
 * One person's view of one list: how they show it, and what they narrow it
 * to, order it by and group it by. A list's layouts are the initiative's; a
 * view is the person's own, kept for them on that list as a view preference
 * (so it follows them from one device to the next), under {@link viewKey}: in
 * the community's map for a list inside a community, in the account's for
 * their own lists across communities.
 *
 * Every list keeps its view here, in one shape:
 *
 * - `layout`: which way they were last looking at it, where it offers several
 *   (a project's list layouts; a collection's masonry, grid or timeline);
 * - `mode`: a calendar's month, week, day or list, or a Gantt's scale;
 * - `parts`: for each layout (one, `LIST`, where there is only one), their
 *   filters, sort, grouping and hidden columns.
 *
 * A list says what its filters are, what someone who set none sees, and what
 * an older release kept for it, which is read until they change something and
 * then kept here. A typed search and a date range are not kept: they are for
 * one visit.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import type { ColumnVisibilityState, GroupingState, SortingState } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef } from "react";

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { useViewPreference, useViewPreferenceMap } from "@/hooks/useViewPreference";
import { getItem } from "@/lib/storage";
import { VIEW_PREFERENCES_QUERY_KEY, viewPreferencesQueryKey } from "@/lib/viewPreferences";
import type { Preset } from "@/ui/layouts/presets";

/** What this device kept under `key` before views followed a person, read
 *  for a carry-over; null where nothing, or nothing readable, is kept. */
export const deviceJSON = (key: string): unknown => {
  try {
    return JSON.parse(getItem(key) ?? "null");
  } catch {
    return null;
  }
};

/** The one part of a list that has no layouts to choose between. */
export const LIST = "list";

/** Where a person's view of a list is kept: `view`, then what names the list.
 *  A list inside a community is kept in that community's map, so its key
 *  names no community (`view:project:12`); a person's own lists across
 *  communities say so (`view:me:tasks`). */
export const viewKey = (...names: (string | number)[]) => ["view", ...names].join(":");

/** A preference map, by key. */
type ViewMap = Readonly<Record<string, unknown>>;

/** One part's view, whole. */
export type PartView<F> = {
  filters: F;
  sorting: SortingState;
  grouping: GroupingState;
  columns: ColumnVisibilityState;
};

/** A view as it is kept: every part of it optional, so what an older release
 *  kept, or what a list never writes, still reads. */
export type StoredListView = {
  layout?: string | null;
  mode?: string | null;
  parts?: Record<string, Partial<Record<keyof PartView<unknown>, unknown>>>;
};

/** What a list says about its view. */
export type ListViewSpec<F> = {
  /** Where it is kept, from {@link viewKey}. */
  key: string;
  /** The community the list is inside, whose map keeps it; none for a
   *  person's own lists across communities, which the account's keeps. */
  communityId?: number;
  /** Their filters as kept, read into the list's shape. */
  read: (raw: unknown) => F;
  /** What someone who has changed nothing sees, for each part. */
  defaults: PartView<F>;
  /** What an older release kept for this list, read where nothing is kept
   *  under `key` yet: from the map that keeps it (`items`), the account's
   *  (`account`, the same map for a list that is the account's own), or the
   *  device. */
  carryOver?: (items: ViewMap, account: ViewMap) => StoredListView | null;
};

const strings = (raw: unknown): string[] | undefined =>
  Array.isArray(raw) ? raw.filter((each): each is string => typeof each === "string") : undefined;

const isSortEntry = (each: unknown): each is SortingState[number] =>
  each !== null &&
  typeof each === "object" &&
  typeof (each as { id?: unknown }).id === "string" &&
  typeof (each as { desc?: unknown }).desc === "boolean";

const isRecord = (raw: unknown): raw is Record<string, unknown> =>
  raw !== null && typeof raw === "object" && !Array.isArray(raw);

/** `raw` as a view, with what has the wrong type dropped, so a stale or
 *  corrupted blob can't break the list. */
export const sanitizeListView = (raw: unknown): StoredListView => {
  if (!isRecord(raw)) return {};
  const parts: NonNullable<StoredListView["parts"]> = {};
  if (isRecord(raw.parts)) {
    for (const [part, entry] of Object.entries(raw.parts)) {
      if (!isRecord(entry)) continue;
      const columns = isRecord(entry.columns)
        ? Object.fromEntries(
            Object.entries(entry.columns).filter(([, shown]) => typeof shown === "boolean")
          )
        : undefined;
      parts[part] = {
        ...(entry.filters !== undefined ? { filters: entry.filters } : {}),
        ...(Array.isArray(entry.sorting) ? { sorting: entry.sorting.filter(isSortEntry) } : {}),
        ...(strings(entry.grouping) ? { grouping: strings(entry.grouping) } : {}),
        ...(columns ? { columns } : {}),
      };
    }
  }
  return {
    layout: typeof raw.layout === "string" ? raw.layout : null,
    mode: typeof raw.mode === "string" ? raw.mode : null,
    parts,
  };
};

/** One part of a kept view, whole: what it keeps, and the list's defaults for
 *  the rest. */
export const partOf = <F>(
  view: StoredListView,
  part: string,
  spec: Pick<ListViewSpec<F>, "read" | "defaults">
): PartView<F> => {
  const kept = view.parts?.[part] ?? {};
  return {
    filters: kept.filters !== undefined ? spec.read(kept.filters) : spec.defaults.filters,
    sorting: (kept.sorting as SortingState | undefined) ?? spec.defaults.sorting,
    grouping: (kept.grouping as GroupingState | undefined) ?? spec.defaults.grouping,
    columns: (kept.columns as ColumnVisibilityState | undefined) ?? spec.defaults.columns,
  };
};

/** The view kept under `spec.key` in `items`, the map that keeps it, or what
 *  an older release kept where nothing is; `account` is the account's map,
 *  for a carry-over from it (`items`, where the list is the account's own).
 *  Shared with route loaders, which read the maps before the list mounts. */
export const keptView = <F>(
  items: ViewMap | undefined,
  spec: Pick<ListViewSpec<F>, "key" | "carryOver">,
  account: ViewMap | undefined = items
): { view: StoredListView } => {
  const raw = items?.[spec.key];
  if (raw != null) return { view: sanitizeListView(raw) };
  // Device carry-overs read with or without a map to read from.
  return { view: sanitizeListView(spec.carryOver?.(items ?? {}, account ?? {}) ?? null) };
};

/** A list inside `communityId` whose view is only which way it is shown (a
 *  counter group's rows or grid): its spec,
 *  carrying over what `older` reads where an older release kept it, on the
 *  account or the device. */
export const layoutViewSpec = (
  communityId: number,
  key: string,
  older: (account: ViewMap) => unknown
): ListViewSpec<null> => ({
  key,
  communityId,
  read: () => null,
  defaults: { filters: null, ...NO_PART_VIEW },
  carryOver: (_items, account) => {
    const layout = older(account);
    return typeof layout === "string" ? { layout } : null;
  },
});

/** The empty filters, sort, grouping and columns. */
export const NO_PART_VIEW = {
  sorting: [] as SortingState,
  grouping: [] as GroupingState,
  columns: {} as ColumnVisibilityState,
};

/**
 * One person's view of the list `spec` names, on its `part`: the layout on
 * screen, or {@link LIST}; or, where that depends on what they kept (the
 * layout they were last in), picked from it. Until the preference map has
 * loaded, it answers the list's defaults with `loaded` false; a table that
 * seeds its sort at mount waits for it.
 */
export function useListView<F>(
  spec: ListViewSpec<F>,
  pick: string | ((view: StoredListView) => string) = LIST
) {
  const queryClient = useQueryClient();
  const [, setRaw, { isLoaded, items }] = useViewPreference<unknown>(
    spec.key,
    null,
    spec.communityId
  );
  // The account's map, for what an older release kept there.
  const account = useViewPreferenceMap();
  const loaded = isLoaded && account.isLoaded;
  const specRef = useRef(spec);
  specRef.current = spec;
  const { read, defaults } = spec;
  const loadedRef = useRef(loaded);
  loadedRef.current = loaded;
  // Changes made before the view is in, applied to it once it is.
  const early = useRef<((kept: StoredListView) => StoredListView)[]>([]);

  // What an older release kept is read once the map is in, until the person
  // changes something, which keeps it here whole: opening a list writes
  // nothing.
  const view = useMemo(
    () =>
      loaded
        ? keptView(items, { key: spec.key, carryOver: specRef.current.carryOver }, account.items)
            .view
        : ({} as StoredListView),
    [loaded, items, account.items, spec.key]
  );

  const part = typeof pick === "function" ? pick(view) : pick;
  const current = useMemo(
    () => partOf(view, part, { read, defaults }),
    [view, part, read, defaults]
  );

  /** Change the kept view, from what is kept now: the cache, so changes made
   *  together compose. Nothing is written when a change leaves it as it was;
   *  a change made before the view is in waits for it, rather than replacing
   *  it. */
  const write = useCallback(
    (patches: ((kept: StoredListView) => StoredListView)[]) => {
      const kept = keptView(
        queryClient.getQueryData<UserViewPreferencesMap>(
          viewPreferencesQueryKey(specRef.current.communityId)
        )?.items,
        specRef.current,
        queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)?.items
      ).view;
      const next = patches.reduce((view, patch) => patch(view), kept);
      if (JSON.stringify(next) !== JSON.stringify(kept)) setRaw(next);
    },
    [queryClient, setRaw]
  );
  const change = useCallback(
    (patch: (kept: StoredListView) => StoredListView) => {
      if (loadedRef.current) write([patch]);
      else early.current.push(patch);
    },
    [write]
  );
  useEffect(() => {
    if (!loaded || early.current.length === 0) return;
    const patches = early.current;
    early.current = [];
    write(patches);
  }, [loaded, write]);

  /** Change this part, keeping `layout` as the one last shown. */
  const changePart = useCallback(
    (patch: Partial<Record<keyof PartView<F>, unknown>>) =>
      change((kept) => ({
        ...kept,
        parts: { ...kept.parts, [part]: { ...kept.parts?.[part], ...patch } },
      })),
    [change, part]
  );

  const setFilters = useCallback(
    (next: F | null | ((prev: F) => F)) =>
      change((kept) => {
        const entry = { ...kept.parts?.[part] };
        if (next === null) delete entry.filters;
        else
          entry.filters =
            typeof next === "function"
              ? (next as (prev: F) => F)(
                  partOf(kept, part, {
                    read: specRef.current.read,
                    defaults: specRef.current.defaults,
                  }).filters
                )
              : next;
        return { ...kept, parts: { ...kept.parts, [part]: entry } };
      }),
    [change, part]
  );
  const setSorting = useCallback(
    (next: SortingState) => changePart({ sorting: next }),
    [changePart]
  );
  const setGrouping = useCallback(
    (next: GroupingState) => changePart({ grouping: next }),
    [changePart]
  );
  const setColumns = useCallback(
    (next: ColumnVisibilityState | ((prev: ColumnVisibilityState) => ColumnVisibilityState)) =>
      change((kept) => {
        const now = partOf(kept, part, {
          read: specRef.current.read,
          defaults: specRef.current.defaults,
        }).columns;
        const columns = typeof next === "function" ? next(now) : next;
        return {
          ...kept,
          parts: { ...kept.parts, [part]: { ...kept.parts?.[part], columns } },
        };
      }),
    [change, part]
  );
  /** Make `filters` and `sorting` this person's own on this part at once. */
  const apply = useCallback(
    (next: { filters: F; sorting?: SortingState }) =>
      changePart({ filters: next.filters, ...(next.sorting ? { sorting: next.sorting } : {}) }),
    [changePart]
  );
  const setMode = useCallback((mode: string) => change((kept) => ({ ...kept, mode })), [change]);
  const rememberLayout = useCallback(
    (layout: string) => change((kept) => ({ ...kept, layout })),
    [change]
  );

  return {
    loaded,
    /** The part on screen. */
    part,
    /** Which way they were last looking at it, where it offers several. */
    layout: view.layout ?? null,
    /** A calendar's month, week, day or list, or null where they never chose. */
    mode: view.mode ?? null,
    ...current,
    /** They picked a grouping on this part, none included, rather than seeing
     *  the default. */
    groupingKept: view.parts?.[part]?.grouping !== undefined,
    setFilters,
    setSorting,
    setGrouping,
    setColumns,
    setMode,
    rememberLayout,
    apply,
  };
}

/**
 * A preset the URL names (`?preset=`) applied as this person's own: once per
 * preset, when the list and their view are in, and dropped from the URL once
 * what they see is no longer the preset's (they changed a filter or the sort,
 * or another layout is on screen). `current` is what they see now; `same`
 * says whether it is still the preset's.
 */
export function usePresetLink<F>({
  slug,
  presets,
  ready,
  scope,
  apply,
  same,
}: {
  slug: string | undefined;
  presets: readonly Preset<F>[];
  /** The list's presets and the person's view are both in. */
  ready: boolean;
  /** What the preset is applied on (the list and its layout): a new scope is a
   *  new pick. */
  scope: string;
  apply: (preset: Preset<F>) => void;
  /** Whether what is on screen is still `preset`'s. */
  same: (preset: Preset<F>) => boolean;
}) {
  const navigate = useNavigate();
  const preset = presets.find((each) => each.slug === slug) ?? null;

  /** Name `next` in the URL, or no preset (undefined). The URL is a link to
   *  the preset while it names one. */
  const name = useCallback(
    (next: string | undefined) =>
      void navigate({
        to: ".",
        search: ((prev: Record<string, unknown>) => ({ ...prev, preset: next })) as never,
        replace: true,
        resetScroll: false,
      }),
    [navigate]
  );

  const applied = useRef<string | null>(null);
  useEffect(() => {
    if (!slug) {
      // Once the URL lets go of a preset, picking it again is a new pick.
      applied.current = null;
      return;
    }
    if (!ready) return;
    if (!preset) {
      name(undefined);
      return;
    }
    const key = `${scope}:${preset.slug}`;
    if (applied.current !== key) {
      applied.current = key;
      apply(preset);
    } else if (!same(preset)) {
      name(undefined);
    }
  }, [slug, ready, preset, scope, apply, same, name]);

  return { preset, pick: name };
}
