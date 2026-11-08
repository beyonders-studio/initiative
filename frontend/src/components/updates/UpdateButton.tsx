import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePendingUpdate } from "@/lib/pendingUpdate";
import { Button } from "@/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

/**
 * The update the app is waiting on, while it is behind: beside the bell, or
 * in the desktop app's title bar while that is drawn. Nothing once the app is
 * up to date.
 */
export const UpdateButton = () => {
  const { t } = useTranslation("common");
  const update = usePendingUpdate();
  if (!update) return null;

  return (
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
  );
};
