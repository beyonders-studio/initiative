import { useParams } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { ShareRequestBatchView } from "@/components/access/ShareRequests";

/** `/share-requests/$batchId` — one ask, where a notification about it lands. */
export const ShareRequestsPage = () => {
  const { t } = useTranslation("access");
  const { batchId } = useParams({ strict: false }) as { batchId: string };
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-semibold text-3xl tracking-tight">{t("answer.batchTitle")}</h1>
      <ShareRequestBatchView batchId={batchId} />
    </div>
  );
};
