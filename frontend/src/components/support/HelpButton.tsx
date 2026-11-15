/**
 * Help, in the desktop app's title bar. It opens and closes the Help panel,
 * which searches the user guide and, where the server takes requests, asks the
 * team. Everywhere else Help is in the account menu and the command center.
 * A dot on it says a request is half written.
 */

import { CircleQuestionMark } from "lucide-react";
import { useTranslation } from "react-i18next";

import { toggleHelp, useHelpDraftWaiting, useHelpOpen } from "@/components/help/helpStore";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

export const HelpButton = () => {
  const { t } = useTranslation("common");
  const open = useHelpOpen();
  const draft = useHelpDraftWaiting();
  const label = t("help");

  return (
    // Carries its own provider, so it works outside the sidebar.
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="relative cursor-pointer text-muted-foreground transition-colors hover:text-foreground aria-expanded:text-foreground"
            aria-label={draft ? `${label}, ${t("helpDraft")}` : label}
            aria-expanded={open}
            onClick={toggleHelp}
          >
            <CircleQuestionMark className="size-4" />
            {draft ? (
              <span
                aria-hidden="true"
                className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-primary"
              />
            ) : null}
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{draft ? t("helpDraft") : label}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
