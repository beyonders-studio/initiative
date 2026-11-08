import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useInitiativeRoster, useInitiativeRosterPages } from "@/hooks/useInitiatives";
import { getUserDisplayName } from "@/lib/userDisplay";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { LoadMore } from "@/ui/load-more";
import { Popover, PopoverContent, PopoverTrigger } from "@/ui/popover";

/** Online faces shown in the row; past this many they fold into a count. */
const FACES = 10;

/**
 * The whole roster, searched on the server and read a page at a time as it is
 * scrolled, so an initiative of thousands opens as fast as one of six.
 */
const RosterList = ({
  initiativeId,
  heading,
  online = false,
}: {
  initiativeId: number;
  heading: string;
  /** Only who is around now. */
  online?: boolean;
}) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const [search, setSearch] = useState("");
  const debounced = useDebouncedValue(search);
  const roster = useInitiativeRosterPages(initiativeId, debounced, true, online);
  const members = roster.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <div className="space-y-2 border-b p-2">
        <p className="px-1 font-medium text-sm">{heading}</p>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("common:search")}
          aria-label={t("common:search")}
          className="h-8"
        />
      </div>
      <div className="max-h-80 overflow-y-auto p-1">
        <ul>
          {members.map((member) => (
            <li key={member.user.id} className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
              <ProfileAvatar
                user={member.user}
                decorations={member.user.profile_decorations}
                presence={member.presence}
                className="h-7 w-7"
              />
              <UserHoverLink
                user={{ ...member.user, presence: member.presence }}
                className="min-w-0 truncate text-sm"
              >
                {getUserDisplayName(member.user)}
              </UserHoverLink>
              {member.role_display_name || member.guest_until ? (
                <span className="ml-auto shrink-0 text-muted-foreground text-xs">
                  {[member.guest_until ? t("detail.guest") : null, member.role_display_name]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              ) : null}
            </li>
          ))}
          {roster.isSuccess && members.length === 0 ? (
            <li className="px-2 py-1.5 text-muted-foreground text-sm">
              {t("common:noResultsDot")}
            </li>
          ) : null}
        </ul>
        {/* The next page as the bottom of the list comes into view. */}
        <LoadMore
          auto
          hasMore={roster.hasNextPage}
          loading={roster.isFetchingNextPage || roster.isLoading}
          onLoadMore={roster.fetchNextPage}
        />
      </div>
    </>
  );
};

/** A count that opens a roster: of everyone, or of who is around now. */
const RosterPopover = ({
  initiativeId,
  label,
  online,
}: {
  initiativeId: number;
  label: string;
  online?: boolean;
}) => (
  <Popover>
    <PopoverTrigger className="rounded-sm underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {label}
    </PopoverTrigger>
    {/* Mounted only while open, which is what keeps the roster unread until
        somebody asks for it. */}
    <PopoverContent align="start" className="w-72 p-0">
      <RosterList initiativeId={initiativeId} heading={label} online={online} />
    </PopoverContent>
  </Popover>
);

/**
 * Who is in an initiative, as people rather than a number.
 *
 * Whoever is around right now shows as a face in the frame they chose, each
 * pointing at the person behind it the way a name anywhere else does. Past ten
 * the faces fold into a count that opens them as a list, as the member count
 * opens everyone. Only the faces are read with the page, so an initiative of
 * thousands costs a handful of rows until somebody looks.
 */
export const InitiativeMembersPeek = ({
  initiativeId,
  memberCount,
}: {
  initiativeId: number;
  memberCount: number;
}) => {
  const { t } = useTranslation("initiatives");
  const here = useInitiativeRoster(initiativeId, { online: true, page_size: FACES });
  const faces = here.data?.items ?? [];
  const online = here.data?.total_count ?? 0;
  const onlineLabel = t("detail.online", { count: online });

  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 align-middle">
      {online > FACES ? (
        <>
          <RosterPopover initiativeId={initiativeId} label={onlineLabel} online />
          <span aria-hidden>·</span>
        </>
      ) : faces.length > 0 ? (
        <>
          {/* The faces say who is here; the count is for a screen reader. */}
          <span className="inline-flex items-center gap-1.5">
            <span className="sr-only">{onlineLabel}</span>
            {faces.map((member) => (
              <UserHoverLink
                key={member.user.id}
                user={{ ...member.user, presence: member.presence }}
                className="rounded-full"
              >
                <ProfileAvatar
                  user={member.user}
                  decorations={member.user.profile_decorations}
                  presence={member.presence}
                  className="h-7 w-7 transition-transform hover:-translate-y-0.5"
                />
              </UserHoverLink>
            ))}
          </span>
          <span aria-hidden>·</span>
        </>
      ) : null}
      <RosterPopover
        initiativeId={initiativeId}
        label={t("detail.member", { count: memberCount })}
      />
    </span>
  );
};
