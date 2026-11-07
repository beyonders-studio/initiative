import { KeyRound, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useDismissHistoryAsk, useHistoryAsk } from "@/hooks/useMyMessages";
import { Button } from "@/ui/button";

/**
 * This device, waiting to be verified by another of the account's and sent
 * the messages it arrived without.
 *
 * The comparison is started on the other device; when it is, the verification
 * dialog opens here too. This says nothing about how long that will take,
 * because nothing here knows: the other device has to be opened by a person
 * before it can answer.
 *
 * It can be put away by hand as well as by the day running out. Dismissing it
 * settles nothing: the ask is still outstanding, and history approved on the
 * other device afterwards still arrives — which is what the closing line says,
 * so nobody reads the button as calling the transfer off.
 */
export const HistoryAskNotice = () => {
  const { t } = useTranslation("messages");
  const ask = useHistoryAsk();
  const dismiss = useDismissHistoryAsk();

  if (!ask.data) return null;

  return (
    <section className="space-y-3 border-b bg-muted/40 px-6 py-4">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium text-sm">{t("historyAsk.title")}</h2>
            <p className="max-w-prose text-muted-foreground text-sm">{t("historyAsk.body")}</p>
          </div>
          <p className="max-w-prose text-muted-foreground text-xs">{t("historyAsk.dismissNote")}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="ml-auto shrink-0 text-muted-foreground"
          aria-label={t("historyAsk.dismiss")}
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate()}
        >
          <X className="size-4" aria-hidden />
        </Button>
      </div>
    </section>
  );
};
