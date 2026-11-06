import type { ReactNode } from "react";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { UserName } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";

interface PersonRowProps {
  /** Decorations travel on the person rather than as a prop of their own, so a
   *  caller that already holds a grant row spreads it and the picture is
   *  dressed. A shape without them — the ignore list — draws a bare one. */
  user: {
    id: number;
    username: string;
    discriminator: number;
    /** Their name in the community the list came from; connections have none. */
    display_name?: string | null;
    avatar_url?: string | null;
    profile_decorations?: ProfileDecorationsOutput | null;
  };
  /** One line under the name — when they connected, what they asked for. */
  detail?: ReactNode;
  /** The row's own controls. */
  children?: ReactNode;
}

/**
 * One person in a connections *ledger* — connections, pending requests, ignored
 * accounts — wherever that ledger is rendered.
 *
 * A list item with buttons, not a row you click through: the thing to do about
 * somebody in a ledger is answer them, so the actions are on the row rather
 * than behind it.
 */
export const PersonRow = ({ user, detail, children }: PersonRowProps) => (
  <li className="flex items-center gap-3 py-2">
    <ProfileAvatar user={user} decorations={user.profile_decorations} className="size-8 shrink-0" />
    <div className="min-w-0 flex-1">
      <UserName user={user} className="text-sm" nameClassName="min-w-0 truncate" />
      {detail ? <p className="truncate text-muted-foreground text-xs">{detail}</p> : null}
    </div>
    {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
  </li>
);
