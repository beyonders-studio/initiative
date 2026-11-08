import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityStatus, SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { openHelp } from "@/components/help/helpStore";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import type { CommunityEntry } from "@/hooks/useCommunities";
import { useCommunityPaymentIssue } from "@/hooks/useCommunityPaymentIssue";
import { useTicketAvailability } from "@/hooks/useTickets";
import { getSessionItem, setSessionItem } from "@/lib/storage";

// The key keeps its old name, so a notice already seen stays dismissed.
const SEEN_KEY_PREFIX = "guild-status-notice:";

const seenThisSession = (key: string): boolean => getSessionItem(SEEN_KEY_PREFIX + key) !== null;

const markSeenThisSession = (key: string) => setSessionItem(SEEN_KEY_PREFIX + key, "1");

export const communityStatusNoticeApplies = (community: CommunityEntry): boolean =>
  community.accessType !== "grant" &&
  community.can.seat &&
  community.status === CommunityStatus.read_only;

type Stage = "notice" | "closed";

export const CommunityStatusNotice = ({ community }: { community: CommunityEntry }) => {
  const { t } = useTranslation(["communities", "common"]);
  const { billing, canSell, openPortal } = useBillingPortal();
  const seenKey = `${community.id}:${community.status}`;
  const [stage, setStage] = useState<Stage>(() =>
    communityStatusNoticeApplies(community) && !seenThisSession(seenKey) ? "notice" : "closed"
  );

  const noticeOpen = stage === "notice";
  const askBilling = noticeOpen && Boolean(billing);
  const issue = useCommunityPaymentIssue(community.id, { enabled: askBilling });
  const paymentFailed = askBilling && issue.data?.payment_failed === true;

  const askSupport = noticeOpen && (!askBilling || issue.isFetched) && !paymentFailed;
  const support = useTicketAvailability(community.id, {
    enabled: askSupport,
    retry: false,
  });
  const offered = support.data?.support;
  // A form where the deployment takes help requests from here; otherwise the
  // address it gave, which is still somebody to ask.
  const contact = offered?.mode === "email" ? offered.contact : null;
  const canAskForHelp = askSupport && (offered?.mode === "form" || contact != null);

  if (stage === "closed") return null;

  if ((askBilling && issue.isPending) || (askSupport && support.isPending)) return null;

  const dismiss = () => {
    markSeenThisSession(seenKey);
    setStage("closed");
  };

  return (
    <AlertDialog open onOpenChange={(open) => !open && dismiss()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {paymentFailed
              ? t("statusNotice.paymentTitle", { name: community.name })
              : t("statusNotice.title")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {paymentFailed
              ? canSell
                ? t("statusNotice.paymentDescription")
                : t("statusNotice.paymentDescriptionInApp")
              : t("statusNotice.description")}
          </AlertDialogDescription>
          <AlertDialogDescription>{t("statusNotice.readOnly")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {paymentFailed && canSell ? (
            <>
              <AlertDialogCancel onClick={dismiss}>{t("statusNotice.notNow")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  markSeenThisSession(seenKey);
                  void openPortal(community.id, "manage");
                }}
              >
                {t("statusNotice.updatePayment")}
              </AlertDialogAction>
            </>
          ) : canAskForHelp ? (
            <>
              <AlertDialogCancel onClick={dismiss}>{t("common:ok")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  markSeenThisSession(seenKey);
                  setStage("closed");
                  // Asked about this community where it takes requests; its
                  // address, at the foot of Help's search, where it gave one.
                  if (contact) openHelp();
                  else openHelp({ topic: SupportTopic.community, communityId: community.id });
                }}
              >
                {t("statusNotice.contactSupport")}
              </AlertDialogAction>
            </>
          ) : (
            <AlertDialogAction onClick={dismiss}>{t("common:ok")}</AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
