import type { UserStatus } from "@/api/generated/initiativeAPI.schemas";
import i18n from "@/i18n";
import { ANONYMIZED_INITIALS, getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { Member } from "@/ui/member-picker";

/**
 * The minimum shape of a user object needed to render a display name.
 *
 * Anything that comes back from the API and represents a person — community
 * member, comment author, task assignee, mention candidate, etc. — should fit
 * this shape. ``status`` is optional because some lightweight endpoints don't
 * include it; absent ``status`` is treated as a live user.
 *
 * ``display_name`` is the person's name in the community the object came
 * from; it is null when they set none, and absent outside a community, where
 * a person is their handle.
 */
export interface DisplayableUser {
  id?: number | null;
  username?: string | null;
  discriminator?: number | null;
  display_name?: string | null;
  status?: UserStatus | string | null;
}

/** ``0012`` — the number as it is always written, four digits. */
export const formatDiscriminator = (discriminator?: number | null): string =>
  discriminator == null ? "" : String(discriminator).padStart(4, "0");

/**
 * ``foobar#1234`` — the handle as one string.
 *
 * For places with no styling to carry the distinction: a title attribute, a
 * copied value, an export. On screen prefer `<UserHandle>`, which renders the
 * number in its own weight.
 */
export const getUserHandle = (user: DisplayableUser | null | undefined): string => {
  if (!user?.username) return "";
  return `${user.username}#${formatDiscriminator(user.discriminator)}`;
};

/**
 * ``jordan1234`` — the handle as one URL segment, which is how a profile is
 * addressed.
 *
 * No ``#``: it never survives a URL. The number keeps its four digits and runs
 * straight on from the name, which stays reversible because the width is
 * fixed — ``user2`` + ``0007`` is ``user20007``, not ``user`` + ``20007``.
 */
export const getUrlHandle = (user: DisplayableUser | null | undefined): string => {
  if (!user?.username) return "";
  return `${user.username}${formatDiscriminator(user.discriminator)}`;
};

/**
 * The single source of truth for "what string do we render for this user".
 *
 * The person's name in this community when they set one, the handle
 * otherwise — and the handle for an account that is no longer in use, whose
 * name the server has already withheld. A handle is never redacted: it is a pseudonym and a unique
 * identifier at once, and an old thread stays legible only if it survives.
 *
 * Use this anywhere you would have written `user.display_name ?? "User"`.
 */
export const getUserDisplayName = (
  user: DisplayableUser | null | undefined,
  fallback?: string
): string => {
  const name = user?.display_name?.trim();
  if (name) return name;
  const handle = getUserHandle(user);
  if (handle) return handle;
  // Nothing to name them by: an id the caller has not resolved yet, or one
  // whose account is gone. The placeholder carries the id when there is one,
  // so two of them stay distinguishable.
  if (fallback !== undefined) return fallback;
  return user?.id != null ? i18n.t("common:userWithId", { id: user.id }) : i18n.t("common:user");
};

/**
 * True when the account has been anonymized (its personal data erased).
 *
 * Centralised so callers don't compare to the magic string everywhere. The
 * handle still renders — this is what decides whether to show a face and a
 * colour that belonged to the person behind it.
 */
export const isAnonymizedUser = (user: DisplayableUser | null | undefined): boolean =>
  user?.status === "anonymized";

/**
 * Whether we hold enough of a user to name them — i.e. whether
 * {@link getUserDisplayName} would return something real rather than the
 * caller's fallback. Pickers use this to decide which selected ids they still
 * need to resolve from the server instead of rendering "User #<id>".
 */
export const hasDisplayName = (user: DisplayableUser | null | undefined): boolean =>
  Boolean(user?.display_name?.trim() || user?.username?.trim());

/**
 * Initials to render in an avatar fallback for the given user. Returns the
 * muted `–` sentinel for anonymized accounts; otherwise takes them from the
 * name, or from the handle when there is no name to take them from.
 */
export const getInitialsForUser = (user: DisplayableUser | null | undefined): string => {
  if (!user) return getInitials(undefined);
  if (user.status === "anonymized") return ANONYMIZED_INITIALS;
  return getInitials(user.display_name ?? undefined, user.username ?? undefined);
};

/** The minimum shape needed to resolve an avatar image source. */
export interface AvatarSourceUser {
  avatar_url?: string | null;
}

/**
 * The single source of truth for "what image src do we render for this user":
 * the picture's URL if they have one, else undefined and the caller falls back
 * to initials. ``avatar_url`` is either a path this server serves the uploaded
 * picture from or one linked from a single sign-on account; both resolve the
 * same way.
 */
export const getAvatarSrc = (user: AvatarSourceUser | null | undefined): string | undefined => {
  if (!user) return undefined;
  return resolveUploadUrl(user.avatar_url ?? undefined) || undefined;
};

/** A person as a picker draws them. */
export const toMember = (user: DisplayableUser & AvatarSourceUser & { id: number }): Member => ({
  id: user.id,
  name: getUserDisplayName(user),
  picture: getAvatarSrc(user),
  initials: getInitialsForUser(user),
});
