import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useMentionedPerson } from "@/hooks/useMentionedPeople";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/ui/lib/utils";

/** The chip itself — the same one comments and documents have always drawn. */
export const MENTION_BADGE = "rounded bg-primary/10 px-1 py-0.5 font-medium text-primary text-sm";

interface UserMentionProps {
  /** Who was named. `null` for somebody with no account here, whom an import
   *  could only name. */
  userId: number | null | undefined;
  /** The name the mention was written with. Empty for anyone with an account
   *  since mentions stopped storing names; older text still carries one, which
   *  stands in until the answer arrives. */
  fallback: string;
  /** The community the mention was written in, where a list spans several.
   *  Defaults to the scope's own. */
  communityId?: number;
  /** Render as plain words — see `UserHoverLink`. */
  disableLink?: boolean;
  className?: string;
}

/**
 * Somebody named, inside prose.
 *
 * The name is read rather than stored: a comment written a year ago says what
 * that person is called today: each mention asks for its person, and a page's
 * asks go out as one request (`useMentionedPerson`). Somebody the answer does not
 * include has left the community, or no longer has an account, and reads as a
 * former member. Until the answer arrives the chip holds its place without
 * guessing at a name.
 */
export const UserMention = ({
  userId,
  fallback,
  communityId,
  disableLink,
  className,
}: UserMentionProps) => {
  const { t } = useTranslation("common");
  const { person, ready, failed } = useMentionedPerson(userId, communityId);

  let label: ReactNode;
  if (person) {
    label = getUserDisplayName(person, fallback);
  } else if (fallback && (userId == null || !ready)) {
    label = fallback;
  } else if (userId == null || ready) {
    // Nobody this community has now, or somebody an export could not name.
    label = t("formerMember");
  } else if (failed) {
    label = <span title={t("mentionNotLoaded")}>…</span>;
  } else {
    label = <span className="animate-pulse">…</span>;
  }

  return (
    <UserHoverLink
      user={person}
      disableLink={disableLink}
      className={cn(
        MENTION_BADGE,
        !disableLink && "hover:bg-primary/20 hover:no-underline",
        className
      )}
    >
      @{label}
    </UserHoverLink>
  );
};
