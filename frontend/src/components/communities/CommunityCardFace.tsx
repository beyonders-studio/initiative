/**
 * The face of a community card: its banner, avatar, name, who is there, where
 * it is if it said, what it says about itself and its shelves. The community directory and the community
 * rail's expanded view both show a community this way; what a card offers below
 * that (join, open, nothing at all) is the caller's.
 *
 * The avatar is passed in rather than drawn here, because the rail's carries
 * marks the directory's never does (unread, closed, a temporary grant).
 */

import { Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityLocationLine } from "@/components/communities/CommunityLocationLine";
import { renderableBanner } from "@/lib/banner";
import { communityCategoryLabel } from "@/lib/communityCategories";
import { Badge } from "@/ui/badge";
import { Card, CardContent } from "@/ui/card";
import { cn } from "@/ui/lib/utils";

export const CommunityCardFace = ({
  community,
  avatar,
  aside,
  meta,
  locationDetails = true,
  className,
  children,
}: {
  community: Pick<
    CommunityRead,
    "name" | "description" | "categories" | "member_count" | "online_count" | "banner" | "location"
  >;
  avatar: ReactNode;
  /** Sits at the end of the name line. */
  aside?: ReactNode;
  /** A further line under who is there. */
  meta?: ReactNode;
  /**
   * Whether the location row opens the place on a map. Off for a card that is itself
   * one button, where it is a plain line instead.
   */
  locationDetails?: boolean;
  className?: string;
  children?: ReactNode;
}) => {
  const { t } = useTranslation(["communities", "common"]);
  // Every card has a banner: the community's artwork, or the colour it wears
  // instead, which costs no fetch at all.
  const banner = renderableBanner(community.banner);

  return (
    // What a report of the listing pictures.
    <Card data-report-target className={cn("flex h-full flex-col overflow-hidden", className)}>
      {banner.image_url ? (
        <img
          src={banner.image_url}
          alt=""
          className="aspect-[4/1] w-full object-cover"
          loading="lazy"
        />
      ) : (
        // Muted under the fill, for an entry whose banner has not arrived (a
        // community reached by a content grant alone carries none).
        <div
          className="aspect-[4/1] w-full bg-muted"
          style={{ backgroundColor: banner.color || undefined }}
          aria-hidden="true"
        />
      )}
      <CardContent className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start gap-3">
          {avatar}
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h3 className="min-w-0 truncate font-semibold text-base" title={community.name}>
                {community.name}
              </h3>
              {aside}
            </div>
            <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
              {/* Who is here now, then how many there are in all. A community with
                  nobody in it says nothing rather than "0 online", which reads
                  as a verdict on the community rather than on the moment. */}
              {community.online_count > 0 ? (
                <>
                  <span className="flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                    <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                    {t("communities:community.onlineCount", { count: community.online_count })}
                  </span>
                  <span aria-hidden="true">·</span>
                </>
              ) : null}
              <span className="flex items-center gap-1">
                <Users className="h-3 w-3" aria-hidden="true" />
                {t("communities:memberCount", { count: community.member_count })}
              </span>
            </p>
            {/* Where it is, on a line of its own: the short reading, with
                anything finer behind a hover or a tap. */}
            {community.location ? (
              <CommunityLocationLine
                location={community.location}
                interactive={locationDetails}
                className="mt-0.5 text-muted-foreground"
              />
            ) : null}
            {meta}
          </div>
        </div>

        <p
          className={
            community.description
              ? "line-clamp-3 text-muted-foreground text-sm"
              : "text-muted-foreground/70 text-sm italic"
          }
        >
          {community.description || t("communities:community.noDescription")}
        </p>

        {community.categories.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {community.categories.map((category) => (
              <Badge key={category} variant="secondary" className="font-normal">
                {communityCategoryLabel(category, t)}
              </Badge>
            ))}
          </div>
        ) : null}

        {children}
      </CardContent>
    </Card>
  );
};
