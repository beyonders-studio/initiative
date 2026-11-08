/**
 * "Report this" wherever something can be reported.
 *
 * The flag, the dialog, and the one rule that holds everywhere: you cannot
 * report your own work. Deleting or editing it is already there, and a report
 * about yourself is somebody else's time.
 *
 * Every surface passes what the thing is and which one — nothing else. Where
 * the report goes is the server's decision, so a caller never has to know
 * whether the thing it is drawn on belongs to a community or to nobody.
 */

import { Flag } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { FileTicketSheet } from "@/components/tickets/FileTicketSheet";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/ui/tooltip";

export interface ReportButtonProps {
  /** A `SearchEntityType` or a `PlatformReportTarget` value. */
  targetType: string;
  targetId: number;
  /** Who made the thing, when it has an author. Hides the button from them. */
  authorId?: number | null;
  /** Override the community sent with the report. Defaults to the active one,
   *  which is right for anything reported from inside a community. */
  communityId?: number | null;
  className?: string;
  size?: "sm" | "icon";
}

export const ReportButton = ({
  targetType,
  targetId,
  authorId,
  communityId,
  className,
  size = "icon",
}: ReportButtonProps) => {
  const { t } = useTranslation("moderation");
  const { user } = useAuth();
  const activeCommunityId = useActiveCommunityId();
  const [open, setOpen] = useState(false);

  // Signed in, and not the author. A signed-out reader has nothing to report
  // with, and the author has delete instead.
  if (!user || (authorId != null && authorId === user.id)) return null;

  return (
    <>
      {/* Its own provider: there is none at the app root, and this button is
          dropped into five different trees. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size={size}
              className={className}
              aria-label={t("report.action")}
              onClick={() => setOpen(true)}
            >
              <Flag className="h-4 w-4" aria-hidden="true" />
              {size === "sm" && <span className="sr-only">{t("report.action")}</span>}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("report.action")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {open && (
        <FileTicketSheet
          open={open}
          onOpenChange={setOpen}
          ticket={{ stream: "moderation", targetType, targetId }}
          communityId={(communityId === undefined ? activeCommunityId : communityId) ?? null}
        />
      )}
    </>
  );
};
