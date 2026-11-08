/**
 * What an idea shows wherever it is listed: its status, under the name the
 * team gave it, and the vote button.
 */

import { useNavigate } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { IdeaRead, IdeaStatusRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useVoteForIdea } from "@/hooks/useIdeas";
import { Toggle } from "@/ui/toggle";

export const IdeaStatusBadge = ({ status }: { status: IdeaStatusRead }) => (
  <span className="inline-flex items-center gap-1.5 font-medium text-foreground text-xs">
    <span
      aria-hidden
      className="size-2 rounded-full bg-muted-foreground"
      style={status.color ? { backgroundColor: status.color } : undefined}
    />
    {status.name}
  </span>
);

/**
 * Vote for an idea, or take the vote back. Somebody signed out is sent to
 * sign in and comes back to `next`, or `onSignIn` does it where there is
 * something to keep first. A closed idea keeps its votes as they are.
 */
export const VoteButton = ({
  idea,
  next,
  onSignIn,
  onVoted,
}: {
  idea: IdeaRead;
  next: string;
  onSignIn?: () => void;
  /** Told once the vote is cast or taken back. */
  onVoted?: (on: boolean) => void;
}) => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const navigate = useNavigate();
  const vote = useVoteForIdea();
  return (
    <Toggle
      variant="outline"
      size="sm"
      pressed={idea.voted}
      disabled={idea.closed || vote.isPending}
      aria-label={t("ideas.voteFor", { title: idea.title })}
      onPressedChange={(on) => {
        if (!user) {
          if (onSignIn) onSignIn();
          else void navigate({ to: "/login", search: { next } });
          return;
        }
        vote.mutate({ taskId: idea.task_id, on }, { onSuccess: () => onVoted?.(on) });
      }}
    >
      {idea.voted ? <Check aria-hidden /> : null}
      {idea.voted ? t("ideas.voted") : t("ideas.vote")}
    </Toggle>
  );
};
