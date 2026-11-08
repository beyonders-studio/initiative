import { BarChart3, Check, Lock, Users, Vote } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PollOptionRead, PostRead } from "@/api/generated/initiativeAPI.schemas";
import { PollVotersDialog } from "@/components/initiativeTools/posts/PollVotersDialog";
import { useRetractPostPollVote, useVoteOnPostPoll } from "@/hooks/usePosts";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { RelativeTime } from "@/ui/relative-time";

interface PostPollProps {
  post: PostRead;
  className?: string;
}

/** The share of the vote one choice took, as a percentage of the people who
 *  answered. Zero when nobody has, rather than a division by nothing. */
const share = (option: PollOptionRead, totalVoters: number | null) =>
  totalVoters && option.vote_count ? Math.round((option.vote_count / totalVoters) * 100) : 0;

/**
 * The question a notice asks, and the answer so far.
 *
 * One row per choice, and the row IS the button — a poll is answered by
 * pointing at what you think, not by pointing at a control beside it. The
 * tally is drawn behind the label rather than in a chart next to it, so the
 * shape of the answer reads at a glance and the words stay legible over it.
 *
 * Three states the same rows have to carry, because the poll decides them and
 * the card cannot:
 *
 * * **Results withheld.** `results_visible` is false while a `hide_results`
 *   poll is open and this reader has not answered, and the server sends no
 *   counts at all — so there is nothing to draw and nothing to guess.
 * * **Closed.** Voting has stopped; the rows become a result rather than a
 *   question, so nothing is clickable and nothing invites a click.
 * * **Answered.** The reader's own choices are marked whether or not anybody
 *   else's are shown, because a voter can always see their own ballot.
 */
export const PostPoll = ({ post, className }: PostPollProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const poll = post.poll;
  const [votersOpen, setVotersOpen] = useState(false);
  const vote = useVoteOnPostPoll(post.id);
  const retract = useRetractPostPollVote(post.id);

  if (!poll) return null;

  const chosen = poll.options.filter((option) => option.voted_by_me).map((option) => option.id);
  const busy = vote.isPending || retract.isPending;
  // A draft's poll is shown but not answerable: the server refuses a vote on a
  // notice nobody has been sent yet, and offering the click would only earn a
  // toast saying so.
  const answerable = !poll.is_closed && post.is_published;

  const pick = (optionId: number) => {
    if (!answerable) return;
    const next = poll.allows_multiple
      ? chosen.includes(optionId)
        ? chosen.filter((id) => id !== optionId)
        : [...chosen, optionId]
      : chosen.includes(optionId)
        ? []
        : [optionId];
    if (next.length === 0) {
      retract.mutate();
      return;
    }
    vote.mutate({ option_ids: next });
  };

  return (
    <section
      className={cn("space-y-2 rounded-lg border bg-card p-3", className)}
      aria-label={poll.question ?? t("poll.heading")}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="inline-flex items-center gap-1.5 font-medium text-sm">
          <Vote className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          {poll.question ?? t("poll.heading")}
        </h3>
        <p className="text-muted-foreground text-xs">
          {poll.allows_multiple ? t("poll.pickSeveral") : t("poll.pickOne")}
        </p>
      </div>

      <ul className="space-y-1.5">
        {poll.options.map((option) => {
          const percent = share(option, poll.total_voters);
          return (
            <li key={option.id}>
              <button
                type="button"
                aria-pressed={option.voted_by_me}
                disabled={!answerable || busy}
                onClick={() => pick(option.id)}
                className={cn(
                  "relative w-full overflow-hidden rounded-md border text-left transition-colors",
                  answerable && !busy && "hover:border-primary/50",
                  option.voted_by_me ? "border-primary/60" : "border-border",
                  !answerable && "cursor-default"
                )}
              >
                {/* The tally, drawn behind the words. `aria-hidden` because the
                    count beside the label already says it — a screen reader
                    should hear the number, not a bar. */}
                {poll.results_visible && (
                  <span
                    aria-hidden
                    className={cn(
                      "absolute inset-y-0 left-0 transition-[width]",
                      option.voted_by_me ? "bg-primary/20" : "bg-muted"
                    )}
                    style={{ width: `${percent}%` }}
                  />
                )}
                <span className="relative flex items-center gap-2 px-3 py-2 text-sm">
                  <span
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-full border",
                      poll.allows_multiple && "rounded-[0.25rem]",
                      option.voted_by_me
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-muted-foreground/40"
                    )}
                  >
                    {option.voted_by_me && <Check className="size-3" aria-hidden />}
                  </span>
                  <span className="min-w-0 flex-1 break-words">{option.text}</span>
                  {poll.results_visible && (
                    <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
                      {t("poll.votes", { count: option.vote_count ?? 0 })}
                      <span className="ml-1">({percent}%)</span>
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground text-xs">
        {poll.results_visible ? (
          <span className="inline-flex items-center gap-1.5">
            <Users className="size-3.5" aria-hidden />
            {t("poll.voters", { count: poll.total_voters ?? 0 })}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <BarChart3 className="size-3.5" aria-hidden />
            {t("poll.resultsAfterVoting")}
          </span>
        )}
        {poll.is_closed ? (
          <span className="inline-flex items-center gap-1.5">
            <Lock className="size-3.5" aria-hidden />
            {t("poll.closed")}
          </span>
        ) : poll.closes_at ? (
          <span className="inline-flex items-center gap-1.5">
            {t("poll.closesLabel")}
            <RelativeTime date={poll.closes_at} />
          </span>
        ) : null}
        {/* The names behind the numbers. Offered only where there are names to
            show: an anonymous poll has none by design, and a poll whose
            results are still withheld would be read out by its own roster. */}
        {!poll.is_anonymous && poll.results_visible && (poll.total_voters ?? 0) > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-auto px-2 py-1 text-xs"
            onClick={() => setVotersOpen(true)}
          >
            {t("poll.whoVoted")}
          </Button>
        )}
        {poll.has_voted && answerable && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-auto px-2 py-1 text-xs"
            disabled={busy}
            onClick={() => retract.mutate()}
          >
            {t("poll.retract")}
          </Button>
        )}
      </div>

      <PollVotersDialog
        open={votersOpen}
        onOpenChange={setVotersOpen}
        postId={post.id}
        options={poll.options}
      />
    </section>
  );
};
