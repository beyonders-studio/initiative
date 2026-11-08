import { Link } from "@tanstack/react-router";

import type { UserSummary } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { getAvatarSrc, getInitialsForUser, getUrlHandle } from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";

/**
 * One member found.
 *
 * A person is not a tool, so this is not the tool row with a different icon:
 * it shows the face and the handle, which is what identifies someone. It opens
 * their profile, which is public and belongs to the person rather than to the
 * community the search ran in — so the link leaves the community tree.
 */
export function MemberResultRow({ member }: { member: UserSummary }) {
  const name = member.display_name?.trim();
  return (
    <Link
      to="/u/$handle"
      params={{ handle: getUrlHandle(member) }}
      className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-accent"
    >
      <Avatar className="h-8 w-8 shrink-0">
        <AvatarImage src={getAvatarSrc(member)} alt="" />
        <AvatarFallback className="text-xs">{getInitialsForUser(member)}</AvatarFallback>
      </Avatar>
      <div className="min-w-0">
        {name && <div className="truncate font-medium">{name}</div>}
        <UserHandle
          user={member}
          className={name ? "text-muted-foreground text-sm" : "font-medium"}
        />
      </div>
    </Link>
  );
}
