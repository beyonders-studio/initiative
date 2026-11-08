import { MessageCircleQuestionMark } from "lucide-react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";

import { hasDraft, openHelp, useHelpState } from "@/components/help/helpStore";

const HelpPanel = lazy(() =>
  import("@/components/help/HelpPanel").then((module) => ({ default: module.HelpPanel }))
);

/**
 * Help, drawn once at the root: the panel while it is open, loaded the first
 * time it is, and while it is closed with a request half written, a pill that
 * opens it again. It renders on every page, signed in or not, so it reads only
 * the preloaded `common` namespace itself.
 */
export const HelpHost = () => {
  const { t } = useTranslation("common");
  const help = useHelpState();
  if (!help.open) {
    return hasDraft(help.draft) ? (
      <button
        type="button"
        onClick={() => openHelp()}
        className="fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 font-medium text-primary-foreground text-sm shadow-lg"
      >
        <MessageCircleQuestionMark className="size-4" aria-hidden="true" />
        {t("helpDraft")}
      </button>
    ) : null;
  }
  return (
    <Suspense fallback={null}>
      <HelpPanel help={help} />
    </Suspense>
  );
};
