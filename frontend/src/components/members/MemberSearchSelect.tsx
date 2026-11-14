import { useEffect, useMemo, useState } from "react";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { type MemberSearchScope, USER_ID_LOOKUP_MAX, useMemberSearch } from "@/hooks/useUsers";
import {
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
  hasDisplayName,
} from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { cn } from "@/ui/lib/utils";

/** The slim user shape these pickers render (the search endpoints' `UserSummary`). */
type MemberSummary = Pick<
  UserSummary,
  "id" | "username" | "discriminator" | "display_name" | "avatar_url" | "status" | "community_role"
>;

/** A member we can render from partial info — a full {@link MemberSummary} from
 *  search, or just an `{ id }` fallback for a selected user we haven't resolved
 *  yet. The display/avatar helpers tolerate the missing fields. */
export type MemberLike = { id: number } & Partial<MemberSummary>;

/** Accumulate display info for users we've seen — from the caller-provided
 *  already-selected set, every search page, and the id lookup below — so a
 *  selected chip keeps its name/avatar even after the query changes and the
 *  row leaves the results.
 *
 *  A selection can also arrive as bare ids with no display info at all: a
 *  filter restored from storage, a stored user-reference property, a page
 *  opened straight onto an existing selection. Those ids are resolved against
 *  the same scoped roster the dropdown searches, so the trigger names them
 *  instead of falling back to "User #<id>". Ids are resolved a lookup page at
 *  a time, so any number of them is named in the end. */
export const useSeenMembers = (
  scope: MemberSearchScope,
  selectedIds: number[],
  selectedUsers: MemberLike[] | undefined,
  results: MemberSummary[]
) => {
  const [seen, setSeen] = useState<Map<number, MemberLike>>(() => new Map());

  const unresolvedIds = useMemo(() => {
    const known = new Map<number, MemberLike>(seen);
    for (const user of [...(selectedUsers ?? []), ...results]) known.set(user.id, user);
    // Sorted so the lookup's query key doesn't churn with selection order.
    return selectedIds.filter((id) => !hasDisplayName(known.get(id))).sort((a, b) => a - b);
  }, [seen, selectedIds, selectedUsers, results]);

  const lookup = useMemberSearch(scope, {
    userIds: unresolvedIds,
    pageSize: USER_ID_LOOKUP_MAX,
    enabled: unresolvedIds.length > 0,
  });
  const resolved = useMemo<MemberSummary[]>(() => lookup.data?.items ?? [], [lookup.data]);

  useEffect(() => {
    setSeen((prev) => {
      const next = new Map(prev);
      let changed = false;
      // Add an id we haven't seen, and upgrade a placeholder we couldn't name
      // once a named record arrives. Every other case must be a no-op — the
      // update has to be idempotent, or a fresh array identity on each render
      // would loop (setState → render → effect → setState).
      for (const user of [...(selectedUsers ?? []), ...results, ...resolved]) {
        const current = next.get(user.id);
        if (current && (hasDisplayName(current) || !hasDisplayName(user))) continue;
        next.set(user.id, user);
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [selectedUsers, results, resolved]);

  return seen;
};

/** A person's picture, or their initials in their own colour. */
export const MemberAvatar = ({ user, className }: { user: MemberLike; className?: string }) => {
  const src = getAvatarSrc(user);
  const label = getUserDisplayName(user);
  return (
    <Avatar className={cn("h-6 w-6 border text-3xs", className)}>
      {src ? <AvatarImage src={src} alt={label} /> : null}
      <AvatarFallback userId={user.id}>{getInitialsForUser(user)}</AvatarFallback>
    </Avatar>
  );
};
