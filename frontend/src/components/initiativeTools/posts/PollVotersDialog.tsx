import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PollOptionRead, PollVoter } from "@/api/generated/initiativeAPI.schemas";
import { PersonRow } from "@/components/connections/PersonRow";
import { usePostPollVoters } from "@/hooks/usePosts";
import type { DialogProps } from "@/types/dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";

type PollVotersDialogProps = DialogProps & {
  postId: number;
  /** The choices, in the order the poll shows them — so the roster reads down
   *  in the same order as the poll it was opened from. */
  options: PollOptionRead[];
};

/**
 * The scrolling roster.
 *
 * The horizontal padding is not decoration: a worn frame is drawn larger than
 * the avatar and hangs outside it on every edge, and a box with
 * `overflow-y: auto` computes its `overflow-x` to `auto` as well — so without
 * room to hang into, the left of every frame is clipped against the edge.
 */
const ROSTER = "max-h-[60vh] space-y-4 overflow-y-auto px-2";

const Group = ({ heading, people }: { heading: string; people: PollVoter[] }) => (
  <section>
    <h3 className="pb-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
      {heading}
    </h3>
    <ul className="divide-y">
      {people.map((person) => (
        <PersonRow key={person.id} user={person} />
      ))}
    </ul>
  </section>
);

/**
 * Who chose what.
 *
 * Grouped by choice rather than listed flat, because the question a roster
 * answers is "who is on which side" — a single list of names would say only
 * that these people answered, which the count already said.
 *
 * The last group is everybody who has not answered: the people the notice was
 * *shared with*, not the whole initiative. Unlike the read roster the author
 * is among them — writing a question does not stop you answering it.
 *
 * This is never opened for an anonymous poll, or for one whose results are
 * still withheld; the server refuses both, and the button that opens it is not
 * offered in either case.
 */
export const PollVotersDialog = ({
  open,
  onOpenChange,
  postId,
  options,
}: PollVotersDialogProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const voters = usePostPollVoters(postId, { enabled: open });

  const byOption = new Map(voters.data?.options.map((entry) => [entry.option_id, entry.voters]));
  const waiting = voters.data?.not_voted ?? [];
  const voted = voters.data?.options.some((entry) => entry.voters.length > 0) ?? false;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("poll.whoVoted")}</DialogTitle>
          <DialogDescription>{t("poll.whoVotedHint")}</DialogDescription>
        </DialogHeader>

        {voters.isLoading ? (
          <div className="flex items-center gap-2 py-6 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : voters.isError ? (
          <p className="py-6 text-destructive text-sm">{t("loadError")}</p>
        ) : (
          <div className={ROSTER}>
            {options.map((option) => {
              const people = byOption.get(option.id) ?? [];
              return people.length > 0 ? (
                <Group
                  key={option.id}
                  heading={t("poll.choiceHeading", {
                    choice: option.text,
                    count: people.length,
                  })}
                  people={people}
                />
              ) : null;
            })}
            {waiting.length > 0 && <Group heading={t("poll.notVoted")} people={waiting} />}
            {waiting.length === 0 && !voted && (
              <p className="py-6 text-center text-muted-foreground text-sm">
                {t("poll.nobodyYet")}
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
