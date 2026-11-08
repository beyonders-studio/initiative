/**
 * "Report this" wherever something can be reported.
 *
 * The flag, the dialog it opens, and the one rule that holds everywhere: you
 * cannot report your own work. Deleting or editing it is already there, and a
 * report about yourself is somebody else's time.
 *
 * Every surface passes what the thing is and which one — nothing else. Where
 * the report goes is the server's decision, so a caller never has to know
 * whether the thing it is drawn on belongs to a community or to nobody.
 */

import { Flag } from "lucide-react";
import { Suspense, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
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

interface Report {
  targetType: string;
  targetId: number;
  communityId: number | null;
  /** The element the thing is drawn in: the nearest marked
   *  `data-report-target` around the button, pictured with the report. */
  thing: Element | null;
}

// The report being written, kept outside React so one dialog, drawn by the app
// shell, serves every button: reporting another thing replaces it.
let current: Report | null = null;
const listeners = new Set<() => void>();
const setReport = (report: Report | null) => {
  current = report;
  for (const listener of listeners) listener();
};
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** The report dialog, drawn once by the app shell. */
export const ReportHost = () => {
  const report = useSyncExternalStore(subscribe, () => current);
  if (!report) return null;
  return (
    // Its own boundary: the first opening loads the dialog's translations.
    <Suspense fallback={null}>
      <FileTicketDialog
        // Another thing reported starts a report of its own.
        key={`${report.targetType}:${report.targetId}`}
        open
        onOpenChange={(open) => {
          if (!open) setReport(null);
        }}
        ticket={{
          stream: "moderation",
          targetType: report.targetType,
          targetId: report.targetId,
          thing: report.thing,
        }}
        communityId={report.communityId}
      />
    </Suspense>
  );
};

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

  // Signed in, and not the author. A signed-out reader has nothing to report
  // with, and the author has delete instead.
  if (!user || (authorId != null && authorId === user.id)) return null;

  return (
    // Its own provider: there is none at the app root, and this button is
    // dropped into five different trees.
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size={size}
            className={className}
            aria-label={t("report.action")}
            onClick={(event) =>
              setReport({
                targetType,
                targetId,
                communityId: (communityId === undefined ? activeCommunityId : communityId) ?? null,
                thing: event.currentTarget.closest("[data-report-target]"),
              })
            }
          >
            <Flag className="h-4 w-4" aria-hidden="true" />
            {size === "sm" && <span className="sr-only">{t("report.action")}</span>}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t("report.action")}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
