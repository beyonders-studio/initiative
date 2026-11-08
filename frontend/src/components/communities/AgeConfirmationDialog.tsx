import { useTranslation } from "react-i18next";

import { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { BirthdateField } from "@/components/auth/BirthdateField";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { HelpLink } from "@/components/support/HelpLink";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";

/**
 * The age question, asked once, before a directory Join goes through.
 *
 * Asked here rather than after the click, so answering is what joins. Once
 * given it is kept on the account, so the second community somebody joins asks
 * nothing. Nowhere else asks at all — a community somebody was invited to is
 * theirs whatever they answer here, and the app around this dialog stays open
 * to an account that closes it without answering.
 *
 * ``onConfirmed`` runs after the answer is recorded and the account refreshed,
 * which is what the caller resumes its join from.
 */
export const AgeConfirmationDialog = ({
  open,
  onOpenChange,
  onConfirmed,
  answerStands,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirmed: () => void;
  /** Override for a caller the server has just told. Omitted, the account's
   *  own record answers it, which is what the directory's card reads. */
  answerStands?: boolean;
}) => {
  const { t } = useTranslation(["communities", "auth", "common"]);
  const { user } = useAuth();
  const { birthdate, setBirthdate, submitting, error, confirm, reset } = useAgeConfirmation(() => {
    onOpenChange(false);
    onConfirmed();
  });

  // The hook outlives the dialog — the card keeps it mounted and only toggles
  // `open` — so closing has to forget the date rather than leaving it for
  // whenever the dialog is opened next.
  const setOpen = (next: boolean) => {
    if (!next) {
      reset();
    }
    onOpenChange(next);
  };

  // An account that answered as under age keeps that answer. Showing the form
  // again would invite it to be re-answered until it came out right, which is
  // the thing recording it exists to stop — so this says what happened and
  // where to go, and offers no second attempt.
  const showsExplanation = answerStands ?? Boolean(user?.age_below_minimum_at);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {showsExplanation ? t("auth:confirmAge.blockedTitle") : t("auth:confirmAge.title")}
          </DialogTitle>
          <DialogDescription>
            {showsExplanation
              ? t("auth:confirmAge.blockedBody")
              : t("communities:community.ageGateBody")}
          </DialogDescription>
        </DialogHeader>
        {showsExplanation ? (
          <>
            <p className="text-muted-foreground text-sm">{t("auth:confirmAge.blockedHelp")}</p>
            <DialogFooter>
              {/* Their own answer, so a question about their account. */}
              <HelpLink
                topic={SupportTopic.account}
                communityId={null}
                variant="ghost"
                onAsk={() => setOpen(false)}
              />
              <Button variant="outline" onClick={() => setOpen(false)}>
                {t("common:close")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <BirthdateField
              id="community-confirm-age"
              value={birthdate}
              onChange={setBirthdate}
              disabled={submitting}
            />
            <p className="text-muted-foreground text-xs">{t("auth:confirmAge.scopeNote")}</p>
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
                {t("common:cancel")}
              </Button>
              <Button onClick={() => void confirm()} disabled={!birthdate || submitting}>
                {submitting ? t("common:submitting") : t("communities:community.ageGateConfirm")}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
