/**
 * Catch me up: what changed that the reader can see since they were last here,
 * in the community or in one tool, written by AI as it arrives. Offered only
 * where AI is on; it costs a request only when it is asked for.
 */

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { catchUp } from "@/api/generated/activity/activity";
import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { type AISummary, SummarySheet } from "@/components/ai/SummarySheet";
import { Button } from "@/components/ui/button";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { dateTimeFormat } from "@/lib/intl";

interface CatchUpButtonProps {
  /** When the reader was last here, or null for the change log's whole week. */
  since: string | null;
  /** The tool it covers, rather than the whole community. */
  scope?: { tool: Tool; toolId: number };
}

export const CatchUpButton = ({ since, scope }: CatchUpButtonProps) => {
  const { t, i18n } = useTranslation("communityHome");
  const communityId = useActiveCommunityId();
  const { isEnabled } = useAIEnabled();
  const [open, setOpen] = useState(false);
  const [told, setTold] = useState<AISummary | null>(null);

  if (!isEnabled) return null;

  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Sparkles className="h-4 w-4" aria-hidden />
        {t("catchUp.button")}
      </Button>
      <SummarySheet
        open={open}
        onOpenChange={setOpen}
        request={(options, signal) =>
          catchUp(
            communityId,
            { since, tool: scope?.tool, tool_id: scope?.toolId },
            options,
            signal
          )
        }
        summary={told}
        onSummaryChange={setTold}
        words={{
          title: t("catchUp.title"),
          intro: t("catchUp.intro"),
          action: t("catchUp.action"),
          writing: t("catchUp.writing"),
          cut: (percent) => t("catchUp.cut", { percent }),
          since: (from) =>
            t("catchUp.since", {
              date: dateTimeFormat(i18n.language, {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(from)),
            }),
          empty: t("catchUp.empty"),
        }}
      />
    </>
  );
};
