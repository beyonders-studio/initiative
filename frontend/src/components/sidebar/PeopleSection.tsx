import { Link } from "@tanstack/react-router";
import { UserRound } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  CommunityRole,
  type CommunityRosterMember,
  type Presence,
} from "@/api/generated/initiativeAPI.schemas";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
} from "@/components/sidebar/sidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useDirectMessagesEnabled, useDmSettings } from "@/hooks/useDirectMessages";
import { useCommunityRoster } from "@/hooks/useUsers";
import { isAdminRole } from "@/lib/permissions";
import { PRESENCE_ORDER, presenceLabelKey } from "@/lib/presence";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const RosterRow = ({ member }: { member: CommunityRosterMember }) => {
  const { t } = useTranslation("communities");
  const status = member.custom_status;
  const away = member.presence === "offline";
  return (
    <SidebarMenuItem>
      <UserHoverLink
        user={member}
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 hover:bg-sidebar-accent hover:no-underline",
          away && "opacity-60"
        )}
      >
        <ProfileAvatar
          user={member}
          decorations={member.profile_decorations}
          presence={member.presence}
          className="size-8 shrink-0"
        />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1 text-sm">
            <span className="truncate">{getUserDisplayName(member)}</span>
            {isAdminRole(member.community_role) && (
              <Badge variant="secondary" className="shrink-0 px-1.5 py-0 text-3xs">
                {member.community_role === CommunityRole.superadmin
                  ? t("members.superadmin")
                  : t("members.admin")}
              </Badge>
            )}
          </span>
          {(status.emoji || status.text) && (
            <span className="block truncate text-muted-foreground text-xs">
              {status.emoji ? <span aria-hidden="true">{status.emoji} </span> : null}
              {status.text}
            </span>
          )}
        </span>
      </UserHoverLink>
    </SidebarMenuItem>
  );
};

/**
 * Who is in this community, by who is here.
 *
 * Somebody this community cannot message is not listed: their direct messages
 * are private, or on "My communities" with this one switched off. A reader in
 * that position is told why they are missing from it.
 */
export const PeopleSection = () => {
  const { t } = useTranslation(["nav", "profiles", "common"]);
  const roster = useCommunityRoster();
  const communityId = useActiveCommunityId();
  const dmEnabled = useDirectMessagesEnabled();
  const dmSettings = useDmSettings().data;
  const readerHidden =
    dmEnabled &&
    (dmSettings?.dm_policy === "private" ||
      (dmSettings?.dm_policy === "community" &&
        dmSettings.communities.some((c) => c.community_id === communityId && !c.enabled)));

  const pages = roster.data?.pages;
  const counts = pages?.[0]?.presence_counts;
  const groups = useMemo(() => {
    // Pages are fetched one at a time from a list ordered by live presence, so
    // somebody whose presence changed in between can come back on two of them.
    const seen = new Set<number>();
    const byPresence = new Map<Presence, CommunityRosterMember[]>();
    for (const member of pages?.flatMap((page) => page.items) ?? []) {
      if (seen.has(member.id)) continue;
      seen.add(member.id);
      const group = byPresence.get(member.presence);
      if (group) group.push(member);
      else byPresence.set(member.presence, [member]);
    }
    return PRESENCE_ORDER.flatMap((presence) => {
      const members = byPresence.get(presence);
      return members ? [{ presence, members }] : [];
    });
  }, [pages]);

  return (
    <SidebarGroup>
      <SidebarGroupLabel className="flex items-center gap-2 py-2">
        <UserRound className="h-4 w-4" />
        <span className="flex-1">{t("people")}</span>
      </SidebarGroupLabel>
      <SidebarGroupContent className="space-y-3">
        {roster.isLoading ? (
          <div className="space-y-2 px-2">
            {[0, 1, 2].map((key) => (
              <div key={key} className="flex items-center gap-2">
                <Skeleton className="size-8 rounded-full" />
                <Skeleton className="h-4 flex-1" />
              </div>
            ))}
          </div>
        ) : roster.isError && !pages ? (
          <div className="space-y-2 px-2">
            <p className="text-muted-foreground text-xs">{t("peopleError")}</p>
            <Button
              variant="outline"
              size="sm"
              className="text-xs"
              onClick={() => void roster.refetch()}
            >
              {t("common:tryAgain")}
            </Button>
          </div>
        ) : groups.length === 0 ? (
          <p className="px-2 text-muted-foreground text-xs">{t("peopleEmpty")}</p>
        ) : (
          groups.map(({ presence, members }) => (
            <section key={presence} aria-label={t(`profiles:${presenceLabelKey(presence)}`)}>
              <h3 className="px-2 pb-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
                {t("peopleGroup", {
                  label: t(`profiles:${presenceLabelKey(presence)}`),
                  count: counts?.[presence] ?? members.length,
                })}
              </h3>
              <SidebarMenu>
                {members.map((member) => (
                  <RosterRow key={member.id} member={member} />
                ))}
              </SidebarMenu>
            </section>
          ))
        )}
        {roster.hasNextPage && (
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs"
            disabled={roster.isFetchingNextPage}
            onClick={() => void roster.fetchNextPage()}
          >
            {t("peopleMore")}
          </Button>
        )}
        {readerHidden && (
          <p className="px-2 text-muted-foreground text-xs">
            {t("peopleReaderHidden")}{" "}
            <Link to="/profile/privacy" className="underline">
              {t("peopleReaderHiddenLink")}
            </Link>
          </p>
        )}
      </SidebarGroupContent>
    </SidebarGroup>
  );
};
