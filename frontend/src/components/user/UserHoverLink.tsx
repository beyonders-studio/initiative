import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { type MiniProfileSummary, UserMiniProfile } from "@/components/user/UserMiniProfile";
import { getUrlHandle } from "@/lib/userDisplay";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/ui/hover-card";
import { cn } from "@/ui/lib/utils";

interface UserHoverLinkProps {
  /** Who is being named. `undefined` where the page has not resolved them —
   *  or where there is nobody to resolve, as with an imported author. */
  user: MiniProfileSummary | null | undefined;
  /** Render as plain words. Set it where this sits inside something that is
   *  already a link, which cannot legally contain one. */
  disableLink?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Somebody's name, as the way to them.
 *
 * Naming someone is the start of wanting to know who they are, so wherever a
 * name is written it opens their profile, and pointing at it shows who they
 * are without going anywhere. On a touch screen there is no pointing, and the
 * tap goes to the profile itself, which is the whole of what the card was
 * summarising.
 *
 * Without a resolved person there is no link to make: a profile is addressed
 * by username and number. Then this is the words and nothing else, which is
 * what a name has always been.
 */
export const UserHoverLink = ({ user, disableLink, className, children }: UserHoverLinkProps) => {
  const handle = getUrlHandle(user);

  if (disableLink || !handle) {
    return <span className={className}>{children}</span>;
  }

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Link to="/u/$handle" params={{ handle }} className={cn("hover:underline", className)}>
          {children}
        </Link>
      </HoverCardTrigger>
      {/* Unpadded, because the banner runs to its edges; the card pads its own
          body. Mounted only while open, which is what makes the profile read
          cost nothing until somebody points at a name. */}
      <HoverCardContent align="start" className="w-72 overflow-hidden p-0">
        <UserMiniProfile handle={handle} summary={user ?? undefined} />
      </HoverCardContent>
    </HoverCard>
  );
};
