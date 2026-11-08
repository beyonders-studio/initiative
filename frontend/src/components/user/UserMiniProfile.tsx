import { useTranslation } from "react-i18next";

import type { Presence, ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ProfileJoined } from "@/components/user/ProfileJoined";
import { isStatusEmpty, StatusBubble } from "@/components/user/ProfileStatus";
import { useUserProfile } from "@/hooks/useUsers";
import { decorationSrc, resolveDecoration, resolveTrophies } from "@/lib/profileDecorations";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Skeleton } from "@/ui/skeleton";

/**
 * As much of a person as a page already holds.
 *
 * Structural rather than one payload's name, because the people who get a card
 * arrive in several shapes — a `UserSummary` from a mention, a `CommentAuthor`
 * from a byline — and the card reads the same five things out of any of them.
 */
export interface MiniProfileSummary extends DisplayableUser, AvatarSourceUser {
  profile_decorations?: ProfileDecorationsOutput | null;
  presence?: Presence;
}

/**
 * The trophy rail at the size a card has.
 *
 * `ProfileTrophies` draws the tray a page stands its trophies out of — a
 * measured thing, the width of six circles with their names printed under
 * them. A card is narrower than that rail's first three, so this shows the
 * same artwork in the same order and names each one in its tooltip instead.
 * The full collection is one click away on the profile itself.
 */
const TrophyRow = ({
  decorations,
}: {
  decorations: ProfileDecorationsOutput | null | undefined;
}) => {
  const { t } = useTranslation("profiles");
  const trophies = resolveTrophies(decorations);
  if (trophies.length === 0) return null;

  return (
    <ul aria-label={t("trophyRail")} className="flex flex-wrap items-center gap-1">
      {trophies.map((trophy) => (
        <li key={trophy.id} className="flex">
          <img
            src={decorationSrc(trophy, decorations?.grad_year)}
            alt={t(trophy.labelKey)}
            title={t(trophy.labelKey)}
            className="block size-8"
          />
        </li>
      ))}
    </ul>
  );
};

/**
 * Who someone is, at a glance — the card a mention of them opens.
 *
 * Laid out like the account menu's own header, because they answer the same
 * question at the same size: the banner they are wearing with what they said
 * they are up to written over it, the picture standing out of its bottom edge,
 * and the name beside it. What follows is what the profile page shows under
 * the picture and nothing more — the trophies, and when they joined.
 *
 * It fetches on mount, and mounting is the hover — the card is not rendered
 * until it opens, so reading a thread costs nothing until somebody points at a
 * name. `summary` is what the page already knows about them, which fills the
 * card immediately and leaves only the banner, status and trophies to arrive.
 */
export const UserMiniProfile = ({
  handle,
  summary,
}: {
  /** The handle as it appears in a URL — see `getUrlHandle`. */
  handle: string;
  /** What the naming page already resolved, drawn while the rest loads. */
  summary?: MiniProfileSummary;
}) => {
  const { t } = useTranslation("profiles");
  const { data: profile, isLoading } = useUserProfile(handle);

  const person = profile ?? summary;
  const decorations = profile?.profile_decorations ?? summary?.profile_decorations;
  const banner = resolveDecoration(decorations?.banner, "banner");
  // A summary carries the name a community shows; a profile deliberately does
  // not, so the two together say more than either. The handle below says who
  // they are when the community shows no names, so this is left out rather
  // than repeated.
  const name = summary?.display_name?.trim() ? getUserDisplayName(summary, "") : "";

  // Nothing came back and nothing was known: the account is gone, or was never
  // this reader's to see. The server does not distinguish them, so neither
  // does this.
  if (!person && !isLoading) {
    return <p className="p-3 text-muted-foreground text-sm">{t("notFound.title")}</p>;
  }

  return (
    <div>
      <div className="relative overflow-hidden">
        {/* Painted rather than placed: artwork with nothing to read in it stays
            out of the reading order, and crops at any width. */}
        <div
          className="h-16 w-full bg-center bg-cover bg-muted"
          style={
            banner
              ? { backgroundImage: `url(${decorationSrc(banner, decorations?.grad_year)})` }
              : undefined
          }
        />
        {/* Over the banner, where there is room for it — the same place the
            account menu puts your own. */}
        {profile && !isStatusEmpty(profile.custom_status) ? (
          <StatusBubble
            status={profile.custom_status}
            className="absolute top-1.5 right-2 max-w-[70%] text-xs"
          />
        ) : null}
        <div className="flex items-end gap-2 px-3 pb-2">
          <ProfileAvatar
            user={person}
            decorations={decorations}
            presence={profile?.presence ?? summary?.presence}
            ring
            className="-mt-6 size-14"
          />
          <div className="min-w-0 flex-1 pb-0.5">
            {name ? <p className="truncate font-semibold text-sm">{name}</p> : null}
            <UserHandle
              user={person}
              className="max-w-full text-muted-foreground text-xs"
              nameClassName="truncate"
            />
          </div>
        </div>
      </div>

      <div className="space-y-2 px-3 pb-3">
        {isLoading && !profile ? <Skeleton className="h-8 w-24" /> : null}
        <TrophyRow decorations={decorations} />
        {profile ? (
          <ProfileJoined joinedAt={profile.joined_at} className="text-muted-foreground text-xs" />
        ) : null}
      </div>
    </div>
  );
};
