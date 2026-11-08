import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityStatus, SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import { openHelp } from "@/components/help/helpStore";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import type { CommunityEntry } from "@/hooks/useCommunities";
import { useCommunityPaymentIssue } from "@/hooks/useCommunityPaymentIssue";
import { useTicketAvailability } from "@/hooks/useTickets";
import { getSessionItem, setSessionItem } from "@/lib/storage";
import { ConfirmDialog } from "@/ui/confirm-dialog";

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

  const offersPayment = paymentFailed && canSell;

  // Closing the notice, by either button, is what marks it seen.
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => !open && dismiss()}
      title={
        paymentFailed
          ? t("statusNotice.paymentTitle", { name: community.name })
          : t("statusNotice.title")
      }
      description={
        <>
          <span className="block">
            {paymentFailed
              ? canSell
                ? t("statusNotice.paymentDescription")
                : t("statusNotice.paymentDescriptionInApp")
              : t("statusNotice.description")}
          </span>
          <span className="mt-2 block">{t("statusNotice.readOnly")}</span>
        </>
      }
      cancelLabel={offersPayment ? t("statusNotice.notNow") : t("common:ok")}
      confirmLabel={
        offersPayment ? t("statusNotice.updatePayment") : t("statusNotice.contactSupport")
      }
      onConfirm={
        offersPayment
          ? () => void openPortal(community.id, "manage")
          : canAskForHelp
            ? () =>
                // Asked about this community where it takes requests; its
                // address, at the foot of Help's search, where it gave one.
                contact
                  ? openHelp()
                  : openHelp({ topic: SupportTopic.community, communityId: community.id })
            : undefined
      }
    />
  );
};
