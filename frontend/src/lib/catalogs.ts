/**
 * What a picture in a catalog may be, and how a wall of them is grouped —
 * mirrored from the server where the server is the authority.
 */

import type { CatalogItemRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { dateTimeFormat } from "@/lib/intl";
import { resolveUploadUrl } from "@/lib/uploadUrl";

/**
 * The most a picture may weigh. `app/services/tenant/catalogs.py` holds the
 * same number and the endpoint refuses anything over it; this copy lets the
 * drop zone say so before a 25 MB upload is attempted rather than after.
 */
export const MAX_IMAGE_BYTES = 25 * 1024 * 1024;

/**
 * What the server's header check recognizes — the raster formats an `<img>`
 * draws. No SVG: a picture in a catalog is drawn, and an SVG is a document
 * that can run. Checked here by MIME type so a drop of mixed files can say
 * which ones it is leaving out; the server checks the bytes.
 */
export const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;

export const ACCEPT_ATTRIBUTE = ACCEPTED_IMAGE_TYPES.join(",");

/** Why a dropped file is not going to be uploaded. */
export type FileRefusal = "type" | "size";

/** Whether this file can be uploaded as a picture, or why not. */
export const refuseFile = (file: File): FileRefusal | null => {
  if (!(ACCEPTED_IMAGE_TYPES as readonly string[]).includes(file.type)) return "type";
  if (file.size > MAX_IMAGE_BYTES) return "size";
  return null;
};

/** What a picture is called: its title, or failing that the name of the
 *  file somebody uploaded — which is at least what they called it. */
export const imageLabel = (image: Pick<CatalogItemRead, "title" | "original_filename">): string =>
  image.title?.trim() || image.original_filename || "";

/** The picture at full size, resolved for wherever the app runs. */
export const imageSrc = (image: Pick<CatalogItemRead, "file_url">): string =>
  resolveUploadUrl(image.file_url) ?? "";

/** The rendition a grid draws: the thumbnail where one was made, the picture
 *  itself where none was. */
export const thumbSrc = (image: Pick<CatalogItemRead, "file_url" | "thumbnail_url">): string =>
  resolveUploadUrl(image.thumbnail_url ?? image.file_url) ?? "";

/** Width over height, or `null` where the size is unknown. What lets a wall
 *  reserve a picture's space before its bytes arrive. */
export const aspectRatio = (image: Pick<CatalogItemRead, "width" | "height">): number | null =>
  image.width && image.height ? image.width / image.height : null;

/** The `YYYY-MM` an item's date falls in — the month the timeline endpoint
 *  files it under. A date is a day, so it is the same wherever it is read. */
export const imagePeriod = (image: Pick<CatalogItemRead, "occurred_on">): string =>
  image.occurred_on.slice(0, 7);

export interface DayGroup<T> {
  /** `YYYY-MM-DD`. */
  day: string;
  items: T[];
}

/**
 * Items grouped by their date, in the order given.
 *
 * The timeline view: items dated the same day sit side by side, and a new
 * day starts a new row. Stable — an item is in exactly one group, and groups
 * keep the list's own order — so a list that arrived newest first groups
 * newest day first.
 */
export const groupByDay = <T extends Pick<CatalogItemRead, "occurred_on">>(
  images: T[]
): DayGroup<T>[] => {
  const groups: DayGroup<T>[] = [];
  for (const image of images) {
    const day = image.occurred_on;
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(image);
    else groups.push({ day, items: [image] });
  }
  return groups;
};

export interface TagGroup<T> {
  /** The tag, or `null` for the pictures that carry none. */
  tag: TagSummary | null;
  items: T[];
}

/**
 * Pictures grouped by tag, tags in the order they first appear.
 *
 * A picture with two tags is under both — "show me everything still awaiting
 * a decision" wants every such picture, wherever else it also is. The
 * untagged pictures come last, under no heading of their own tag, so a wall
 * that is mostly untagged reads as the wall it was with a few named sections
 * above it.
 */
export const groupByTag = <T extends Pick<CatalogItemRead, "tags">>(images: T[]): TagGroup<T>[] => {
  const byTag = new Map<number, TagGroup<T>>();
  const untagged: T[] = [];
  for (const image of images) {
    if (image.tags.length === 0) {
      untagged.push(image);
      continue;
    }
    for (const tag of image.tags) {
      const group = byTag.get(tag.id);
      if (group) group.items.push(image);
      else byTag.set(tag.id, { tag, items: [image] });
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
