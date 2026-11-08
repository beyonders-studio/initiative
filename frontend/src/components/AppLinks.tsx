import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { HelpButton } from "@/components/support/HelpButton";
import { usePendingUpdate } from "@/lib/pendingUpdate";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/**
 * The app's corner: the update it is waiting on, while it is behind, and Help.
 * Drawn under the person in the sidebar, and in the desktop app's title bar
 * as well.
 */
export const AppLinks = ({ className }: { className?: string }) => {
  const { t } = useTranslation("common");
  const update = usePendingUpdate();

  return (
    <div className={cn("flex items-center gap-3", className)}>
      {update ? (
        // Carries its own provider, so it works outside the sidebar.
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" className="h-6 rounded-full px-2.5 text-xs" onClick={update.run}>
                <Download className="size-3.5" />
                {t("appUpdate.update")}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{t(`appUpdate.action.${update.action}`)}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : null}
      <HelpButton />
    </div>
  );
};
