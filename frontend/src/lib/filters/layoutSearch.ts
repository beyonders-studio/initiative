/**
 * The search params that name one of a target's layouts: `?layout=` on a list,
 * which of its list layouts it shows, and on the layout editor, which layout
 * it opens on. A list's `?preset=` names one of its layout's presets.
 */

import { DetailLayoutReadKind, ListLayoutReadKind } from "@/api/generated/initiativeAPI.schemas";

const LISTS: readonly string[] = Object.values(ListLayoutReadKind);
const KINDS: readonly string[] = [...LISTS, ...Object.values(DetailLayoutReadKind)];

/** Coerce a list's `?layout=`. Anything else is dropped, never thrown — a
 *  pasted link with a typo should still render the list. */
export const parseListLayout = (raw: unknown): ListLayoutReadKind | undefined =>
  typeof raw === "string" && LISTS.includes(raw) ? (raw as ListLayoutReadKind) : undefined;

/** A project's task page for one task type: `task:<type id>`. */
const TYPED_DETAIL = /^task:[1-9][0-9]{0,9}$/;

/** Coerce the layout editor's `?layout=`, which may also name a detail, or one
 *  task type's page (`task:12`). */
export const parseLayoutKind = (raw: unknown): string | undefined =>
  typeof raw === "string" && (KINDS.includes(raw) || TYPED_DETAIL.test(raw)) ? raw : undefined;

/** What a preset's slug is written in, as the server allows. */
const SLUG_CHARS = new Set("abcdefghijklmnopqrstuvwxyz0123456789-");
const MAX_SLUG_LENGTH = 64;

/** Coerce a list's `?preset=`: a slug, or nothing. Whether the layout offers
 *  it is the list's to say. */
export const parsePreset = (raw: unknown): string | undefined =>
  typeof raw === "string" &&
  raw.length > 0 &&
  raw.length <= MAX_SLUG_LENGTH &&
  [...raw].every((char) => SLUG_CHARS.has(char))
    ? raw
    : undefined;
