import { useTranslation } from "react-i18next";

import type {
  CustomStatusOutput,
  Presence,
  ProfileDecorationsOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { PresenceDot } from "@/components/user/PresenceDot";
import { PresenceMenu } from "@/components/user/PresenceMenu";
import { ProfileJoined } from "@/components/user/ProfileJoined";
import { ProfilePicture } from "@/components/user/ProfilePicture";
import { ProfileStatus } from "@/components/user/ProfileStatus";
import { ProfileTrophies } from "@/components/user/ProfileTrophies";
import { presenceLabelKey } from "@/lib/presence";
import { decorationSrc, resolveDecoration } from "@/lib/profileDecorations";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";
import { Card, CardContent } from "@/ui/card";

interface ProfilePreviewProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations: ProfileDecorationsOutput;
  status: CustomStatusOutput;
  /** What the account is set to appear as. */
  presence: Presence;
  /** ISO date the account was created. */
  joinedAt: string;
  /** Re-read the account after anything set from the card is changed. */
  onChanged?: () => Promise<void> | void;
}

/**
 * Your profile as everyone else sees it, at the size a settings tab has.
 *
 * The page itself runs its banner the full width of the content area, the way
 * a community's front page does. That is a page's shape, not a panel's, so
 * this keeps the banner inside a card and shares the parts instead — the same
 * avatar, status, trophy rail and joined line the page draws, in the same
 * order, so what you see here cannot say something the page does not.
 *
 * The card is also the controls: the picture, the status and the presence dot
 * are all set by clicking them here, because the thing you are looking at is
 * the thing you want to change and a section further down would be a second
 * place to keep in agreement with this one. The dot is the one control that
 * has to sit outside the picture rather than on it — the picture is a button,
 * and a button inside a button belongs to neither.
 */
export const ProfilePreview = ({
  user,
  decorations,
  status,
  presence,
  joinedAt,
  onChanged,
}: ProfilePreviewProps) => {
  const { t } = useTranslation("profiles");
  const banner = resolveDecoration(decorations.banner, "banner");

  return (
    <Card className="overflow-hidden pt-0">
      {/* Painted rather than placed: a background keeps artwork with nothing
          to read in it out of the reading order, and lets it crop at any width. */}
      <div
        className="h-28 w-full bg-center bg-cover bg-muted sm:h-36"
        style={
          banner
            ? { backgroundImage: `url(${decorationSrc(banner, decorations.grad_year)})` }
            : undefined
        }
      />
      <CardContent className="space-y-4 pt-4">
        {/* The status above the picture, the same way the page has it: the
            bubble is a thought and the face under it is who is thinking. */}
        <div className="space-y-1">
          <ProfileStatus status={status} editable onSaved={onChanged} />
          <div className="flex flex-wrap items-end gap-4">
            <div className="relative">
              <ProfilePicture
                user={user}
                decorations={decorations}
                hidePresence
                editable
                onChanged={onChanged}
                className="size-24 sm:size-28"
              />
              <PresenceMenu presence={presence} onChanged={onChanged}>
                <button
                  type="button"
                  className="absolute right-0 bottom-0 rounded-full ring-2 ring-card transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
                  aria-label={t("presence.change", { state: t(presenceLabelKey(presence)) })}
                >
                  <PresenceDot presence={presence} className="size-6 sm:size-7" />
                </button>
              </PresenceMenu>
            </div>
            <div className="flex min-w-0 flex-wrap items-center pb-1">
              <UserHandle user={user} className="font-semibold text-2xl" />
            </div>
            <ProfileJoined joinedAt={joinedAt} className="ms-auto pb-1" />
          </div>
        </div>

        {/* The rail under the picture, where the page has it. Nothing
            follows it here — the communities the page shelves in this tray are
            a read of someone else's profile — so it closes into a bar. */}
        <ProfileTrophies decorations={decorations} />
      </CardContent>
    </Card>
  );
};
