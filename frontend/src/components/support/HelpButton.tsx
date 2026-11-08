/**
 * Help, in the app's corner (`AppLinks`): the sidebar's bottom row, or the
 * desktop app's title bar. It opens and closes the Help panel, which searches
 * the user guide and, where the server takes requests, asks the team.
 */

import { CircleQuestionMark } from "lucide-react";
import { useTranslation } from "react-i18next";

import { toggleHelp, useHelpOpen } from "@/components/help/helpStore";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

export const HelpButton = () => {
  const { t } = useTranslation("common");
  const open = useHelpOpen();
  const label = t("help");

  return (
    // Carries its own provider, so it works outside the sidebar.
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground aria-expanded:text-foreground"
            aria-label={label}
            aria-expanded={open}
            onClick={toggleHelp}
          >
            <CircleQuestionMark className="size-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <p>{label}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
