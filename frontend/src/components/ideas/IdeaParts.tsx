/**
 * What a suggestion shows wherever it is listed: its status, under the name
 * and icon the team gave it, its category beside it, and the upvote.
 */

import { useNavigate } from "@tanstack/react-router";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { IdeaRead, IdeaStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { ReactionChip } from "@/components/reactions/ReactionChip";
import { useAuth } from "@/hooks/useAuth";
import { useVoteForIdea } from "@/hooks/useIdeas";
import { Icon, type IconName } from "@/ui/icon-picker";
import { cn } from "@/ui/lib/utils";

/** What an upvote is drawn with. */
const UPVOTE = "👍";

/** A status in its colour, by its icon, and its name. */
export const IdeaStatusBadge = ({
  status,
  className,
}: {
  status: IdeaStatusRead;
  /** The name's colour, where the foreground's is not the one. */
  className?: string;
}) => (
  <span className={cn("inline-flex items-center gap-1.5 font-medium text-foreground", className)}>
    {status.icon ? (
      <Icon
        name={status.icon as IconName}
        aria-hidden
        className="size-4 shrink-0 text-muted-foreground"
        style={status.color ? { color: status.color } : undefined}
      />
    ) : (
      <span
        aria-hidden
        className="size-2 rounded-full bg-muted-foreground"
        style={status.color ? { backgroundColor: status.color } : undefined}
      />
    )}
    {status.name}
  </span>
);

/** A suggestion's category, where it has one, and its status. */
export const IdeaMeta = ({ idea, onDark = false }: { idea: IdeaRead; onDark?: boolean }) => (
  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
    {idea.category ? (
      <>
        <span className={onDark ? "text-slate-300" : "text-muted-foreground"}>{idea.category}</span>
        <span aria-hidden className={onDark ? "text-white/30" : "text-muted-foreground"}>
          ·
        </span>
      </>
    ) : null}
    <IdeaStatusBadge status={idea.status} className={onDark ? "text-white" : undefined} />
  </div>
);

/**
 * Upvote a suggestion, or take the upvote back: the reaction chip's 👍 and
 * the count. Somebody signed out is sent to sign in and comes back to `next`,
 * or `onSignIn` does it where there is something to keep first. A closed
 * suggestion keeps its votes as they are, and shows them as text.
 */
export const VoteButton = ({
  idea,
  next,
  onSignIn,
  onVoted,
  size = "default",
}: {
  idea: IdeaRead;
  next: string;
  onSignIn?: () => void;
  /** Told once the vote is cast or taken back. */
  onVoted?: (on: boolean) => void;
  size?: "default" | "lg";
}) => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const navigate = useNavigate();
  const vote = useVoteForIdea();
  const signInNote = useId();
  // What the last vote did, said once it is saved.
  const [said, setSaid] = useState("");

  if (idea.closed) {
    return (
      <span
        role="img"
        aria-label={t("ideas.closedVotes", { count: idea.votes })}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 px-1.5 text-muted-foreground",
          size === "lg" ? "h-11 text-sm sm:h-9" : "h-7 text-xs"
        )}
      >
        <span aria-hidden className={cn("leading-none grayscale", size === "lg" && "text-base")}>
          {UPVOTE}
        </span>
        <span aria-hidden className="tabular-nums">
          {idea.votes}
        </span>
      </span>
    );
  }

  const press = () => {
    if (!user) {
      if (onSignIn) onSignIn();
      else void navigate({ to: "/login", search: { next } });
      return;
    }
    if (vote.isPending) return;
    const on = !idea.voted;
    vote.mutate(
      { taskId: idea.task_id, on },
      {
        onSuccess: (read) => {
          setSaid(t(on ? "ideas.upvoted" : "ideas.upvoteTakenBack", { count: read.votes }));
          onVoted?.(on);
        },
      }
    );
  };

  return (
    <>
      <ReactionChip
        emoji={UPVOTE}
        count={idea.votes}
        pressed={idea.voted}
        size={size}
        greyscale
        tick={said !== ""}
        className="shrink-0"
        onClick={press}
        aria-label={t("ideas.upvote", { count: idea.votes, title: idea.title })}
        aria-describedby={user ? undefined : signInNote}
      />
      {user ? null : (
        <span id={signInNote} hidden>
          {t("ideas.signInToVote")}
        </span>
      )}
      <span className="sr-only" aria-live="polite">
        {said}
      </span>
    </>
  );
};
