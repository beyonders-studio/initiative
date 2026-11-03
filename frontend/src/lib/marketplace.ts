import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

/**
 * Which marketplace offers a listing.
 *
 * Most kinds install to a **community** — a dashboard lands in an initiative,
 * a plug-in mounts in a community, and installing is something a community's
 * admins do. A profile pack and a home layout install to a **person**: a
 * pack's decorations land in one account's library, a layout becomes a view on
 * their own home page, and either belongs to that person across every
 * community they are in.
 *
 * That is why there are two marketplaces rather than one with a filter. They
 * have different shelves, different buyers and different answers to "do I
 * already have this" — a community's install is shared, a person's is theirs.
 *
 * Mirrors ``KIND_AUDIENCE`` in ``backend/app/services/marketplace/
 * definitions.py``, which is the source of truth; a kind missing from both
 * lists here is offered by neither, which the test below refuses.
 */
export const USER_SHELVES = [ListingKind.home_layout, ListingKind.profile_pack] as const;

export const COMMUNITY_SHELVES = [
  ListingKind.dashboard,
  ListingKind.project,
  ListingKind.plugin,
  ListingKind.auto,
] as const;

/**
 * Kinds the server publishes that no shelf shows yet: the tool marketplaces
 * other than dashboards and projects. Each one exists in the API — browse,
 * detail and install — and is surfaced by moving it into `COMMUNITY_SHELVES`.
 */
export const UNSHELVED_KINDS = [
  ListingKind.file,
  ListingKind.queue,
  ListingKind.counter_group,
  ListingKind.calendar,
  ListingKind.post,
  ListingKind.wiki,
] as const;

/** A shelf a community installs from — the values `?kind=` may name under
 *  `/c/{id}/marketplace`. Derived from the list above so a shelf added there is
 *  a shelf the URL accepts, with nothing else to update. */
export type CommunityShelf = (typeof COMMUNITY_SHELVES)[number];

/** Where the community marketplace opens when the URL names no shelf, and what
 *  a `kind` it does not sell normalizes to. */
export const DEFAULT_COMMUNITY_SHELF: CommunityShelf = ListingKind.dashboard;

const LISTING_KINDS: ReadonlySet<string> = new Set(Object.values(ListingKind));
const COMMUNITY_SHELF_KINDS: ReadonlySet<string> = new Set(COMMUNITY_SHELVES);
const USER_SHELF_KINDS: ReadonlySet<string> = new Set(USER_SHELVES);

const isListingKind = (value: unknown): value is ListingKind =>
  typeof value === "string" && LISTING_KINDS.has(value);

const isCommunityShelf = (value: unknown): value is CommunityShelf =>
  typeof value === "string" && COMMUNITY_SHELF_KINDS.has(value);

/**
 * A `kind` URL param as the kind the server named, or undefined when it names
 * none.
 *
 * Both marketplace routes read `kind` through this rather than each spelling
 * out the values it accepts: the enum the API generates is the list, so a kind
 * added server-side is one the URL understands as soon as the types are
 * regenerated.
 */
export const parseListingKind = (value: unknown): ListingKind | undefined =>
  isListingKind(value) ? value : undefined;

/** The same, narrowed to what a community's marketplace sells. Anything else —
 *  a person's shelf, a typo, nothing at all — opens the default shelf. */
export const parseCommunityShelf = (value: unknown): CommunityShelf =>
  isCommunityShelf(value) ? value : DEFAULT_COMMUNITY_SHELF;

/** Whether this kind is bought by a person rather than by a community. */
export const isUserShelf = (kind: ListingKind): boolean => USER_SHELF_KINDS.has(kind);

/** The region of a BCP 47 tag (`en-US` → `US`), or null when it names none. */
const regionOf = (tag: string | undefined): string | null => {
  if (!tag) return null;
  try {
    return new Intl.Locale(tag).region ?? null;
  } catch {
    return null;
  }
};

/** The minimum age a plug-in declares for somebody in the viewer's region: the
 *  region's own entry, else `default`, else null (the plug-in sets none beyond
 *  the deployment's). The region comes from the browser's language tag, the
 *  only place a listing page can learn one; it is a hint for display, not a
 *  gate. */
export const minimumAgeFor = (
  definition: Record<string, unknown> | null | undefined,
  languageTag: string | undefined
): number | null => {
  const declared = definition?.minimum_age;
  if (!declared || typeof declared !== "object") return null;
  const ages = declared as Record<string, unknown>;
  const region = regionOf(languageTag);
  const age = (region ? ages[region] : undefined) ?? ages.default;
  return typeof age === "number" ? age : null;
};
