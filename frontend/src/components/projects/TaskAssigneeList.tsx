import { useTranslation } from "react-i18next";

import type { TaskAssigneeSummary, UserPublic } from "@/api/generated/initiativeAPI.schemas";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getInitialsForUser, getUserDisplayName, isAnonymizedUser } from "@/lib/userDisplay";
import { Avatar, AvatarFallback, AvatarImage } from "@/ui/avatar";
import { listFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

type Assignee = UserPublic | TaskAssigneeSummary;

interface TaskAssigneeListProps {
  assignees: Assignee[];
  size?: "sm" | "md";
  className?: string;
}

const sizeStyles = {
  sm: {
    avatar: "h-4 w-4 text-3xs",
    text: "text-xs",
  },
  md: {
    avatar: "h-8 w-8 text-xs",
    text: "text-sm",
  },
};

const AssigneeAvatar = ({ assignee, className }: { assignee: Assignee; className?: string }) => {
  const anonymized = isAnonymizedUser(assignee);
  const displayName = getUserDisplayName(assignee);
  // Suppress avatar image and the deterministic colour fallback for
  // anonymized rows — both are derived from the prior user's identity.
  const avatarSrc = anonymized ? undefined : resolveUploadUrl(assignee.avatar_url) || undefined;
  return (
    <Avatar className={cn("border", className)}>
      {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
      <AvatarFallback userId={anonymized ? null : assignee.id}>
        {getInitialsForUser(assignee)}
      </AvatarFallback>
    </Avatar>
  );
};

export const TaskAssigneeList = ({ assignees, size = "sm", className }: TaskAssigneeListProps) => {
  if (!assignees.length) {
    return null;
  }

  const styles = sizeStyles[size];

  return (
    <div className={cn("flex flex-wrap gap-3 text-muted-foreground", className)}>
      {assignees.map((assignee) => (
        <div key={assignee.id} className="flex items-center gap-1">
          <AssigneeAvatar assignee={assignee} className={styles.avatar} />
          <span className={cn("font-medium", styles.text)}>{getUserDisplayName(assignee)}</span>
        </div>
      ))}
    </div>
  );
};

// One size whether a row has one assignee or several, so the column lines up.
const STACK_AVATAR = "h-6 w-6 border-2 border-background text-3xs";

/**
 * Assignees where a row has little room: one is named beside their avatar;
 * more sit as one overlapping stack, which spreads apart under the pointer or
 * focus so each can be pointed at for their name.
 */
export const TaskAssigneeStack = ({
  assignees,
  className,
}: {
  assignees: Assignee[];
  className?: string;
}) => {
  const { i18n } = useTranslation();
  if (assignees.length === 0) return null;
  if (assignees.length === 1) {
    const [assignee] = assignees;
    return (
      <div className={cn("flex min-w-0 items-center gap-1.5 text-muted-foreground", className)}>
        <AssigneeAvatar assignee={assignee} className={STACK_AVATAR} />
        <span className="truncate font-medium text-xs">{getUserDisplayName(assignee)}</span>
      </div>
    );
  }
  const names = assignees.map((assignee) => getUserDisplayName(assignee));
  return (
    <TooltipProvider delayDuration={150}>
      <ul
        className={cn("group/assignees flex items-center", className)}
        aria-label={listFormat(i18n.resolvedLanguage ?? i18n.language, {
          type: "conjunction",
        }).format(names)}
      >
        {assignees.map((assignee, index) => (
          <li
            key={assignee.id}
            className={cn(
              "transition-[margin] duration-150 ease-out motion-reduce:transition-none",
              index > 0 && "-ml-2 group-focus-within/assignees:ml-1 group-hover/assignees:ml-1"
            )}
          >
            <Tooltip>
              <TooltipTrigger
                type="button"
                className="block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={names[index]}
              >
                <AssigneeAvatar assignee={assignee} className={STACK_AVATAR} />
              </TooltipTrigger>
              <TooltipContent>{names[index]}</TooltipContent>
            </Tooltip>
          </li>
        ))}
      </ul>
    </TooltipProvider>
  );
};
