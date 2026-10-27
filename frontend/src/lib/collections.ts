/**
 * How a collection's files are laid out on its wall and grouped: the wall a
 * gallery was, of files rather than pictures.
 */

import { Layers } from "lucide-react";

import type {
  CollectionFileSummary,
  FileSummary,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { localDayKey } from "@/lib/formatDate";
import { dateTimeFormat } from "@/lib/intl";

/** The mark a collection is drawn with, wherever one is named. */
export const COLLECTION_ICON = Layers;

/** The shape a file stands at on the wall and the timeline when it has no
 *  size of its own: a landscape, the space a wall can reserve for it. */
export const FILE_TILE_RATIO = 4 / 3;

/** Width over height: a picture's own, measured when its thumbnail was
 *  drawn, else {@link FILE_TILE_RATIO}. What lets a wall reserve a file's
 *  space before its bytes arrive. */
export const fileRatio = (file: Pick<FileSummary, "width" | "height">): number =>
  file.width && file.height ? file.width / file.height : FILE_TILE_RATIO;

/** The day a file was added to its collection, `YYYY-MM-DD` in the reader's
 *  zone: what the timeline files it under. */
export const arrivalDay = (file: Pick<CollectionFileSummary, "added_at">): string =>
  localDayKey(file.added_at);

export interface DayGroup<T> {
  /** `YYYY-MM-DD`. */
  day: string;
  items: T[];
}

/**
 * Files grouped by the day they were added to the collection, in the order
 * given.
 *
 * The timeline view: files from the same day sit side by side, and a new day
 * starts a new row. Stable — a file is in exactly one group, and groups keep
 * the list's own order — so a list that arrived newest first groups newest
 * day first.
 */
export const groupByDay = <T extends Pick<CollectionFileSummary, "added_at">>(
  files: T[]
): DayGroup<T>[] => {
  const groups: DayGroup<T>[] = [];
  for (const file of files) {
    const day = arrivalDay(file);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(file);
    else groups.push({ day, items: [file] });
  }
  return groups;
};

export interface TagGroup<T> {
  /** The tag, or `null` for the files that carry none. */
  tag: TagSummary | null;
  items: T[];
}

/**
 * Files grouped by tag, tags in the order they first appear.
 *
 * A file with two tags is under both — "show me everything still awaiting a
 * decision" wants every such file, wherever else it also is. The untagged
 * come last, so a wall that is mostly untagged reads as the wall it was with a
 * few named sections above it.
 */
export const groupByTag = <T extends Pick<FileSummary, "tags">>(files: T[]): TagGroup<T>[] => {
  const byTag = new Map<number, TagGroup<T>>();
  const untagged: T[] = [];
  for (const file of files) {
    if (file.tags.length === 0) {
      untagged.push(file);
      continue;
    }
    for (const tag of file.tags) {
      const group = byTag.get(tag.id);
      if (group) group.items.push(file);
      else byTag.set(tag.id, { tag, items: [file] });
    }
  }
  const groups = [...byTag.values()];
  if (untagged.length > 0) groups.push({ tag: null, items: untagged });
  return groups;
};

/** The day a group is labelled with, in the browser's locale — "Tuesday, 3
 *  March 2026". Returns the raw day if it is not one. */
export const formatDay = (day: string): string => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return dateTimeFormat(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
};
